"""Bitpanda Portfolio Intelligence — read-only Streamlit page."""
from datetime import datetime, timezone
import json

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from bitpanda import BitpandaClient, BitpandaAPIError, BitpandaPortfolioStore, BitpandaStoreError

st.set_page_config(page_title="Bitpanda Portfolio Intelligence | MID", layout="wide")
st.title("Bitpanda Portfolio Intelligence")
st.caption("Connexió de només lectura · actualització automàtica cada 15 minuts")
st.warning("READ ONLY · Aquesta pàgina no pot executar compres, vendes, staking ni retirades.")

def secret(key):
    try:
        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""

password = secret("DASHBOARD_PASSWORD")
if not password:
    st.error("Falta DASHBOARD_PASSWORD a les secrets del desplegament.")
    st.stop()
if st.session_state.get("dashboard_authenticated") is not True:
    if st.text_input("Contrasenya del dashboard", type="password", key="bitpanda_password") != password:
        st.stop()
    st.session_state["dashboard_authenticated"] = True

api_key = secret("BITPANDA_API_KEY")
supabase_url = secret("SUPABASE_URL")
supabase_key = secret("SUPABASE_SERVICE_ROLE_KEY")
if not api_key:
    st.info("Per activar aquesta pàgina, crea una clau Bitpanda v2 de només lectura i afegeix BITPANDA_API_KEY a les secrets del hosting.")
    st.markdown("Permisos necessaris: **Balances**, **Transaction**, **Trade (Read)** i **Earn (Read)**. No activis cap permís Write.")
    st.stop()
if not supabase_url or not supabase_key:
    st.error("Falten SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY.")
    st.stop()

st_autorefresh(interval=900_000, limit=None, key="bitpanda-15m-refresh")

@st.cache_data(ttl=900, show_spinner=False)
def fetch_bitpanda_data(key, database_url, database_key):
    client = BitpandaClient(key)
    result = {
        "holdings": client.get_holdings(),
        "operations": client.get_operations(max_pages=5),
        "history": {
            timeframe: client.get_history(timeframe)
            for timeframe in ("MONTH", "SIX_MONTH", "YEAR")
        },
        "earn": client.get_earn_configs(max_pages=5),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    store = BitpandaPortfolioStore(database_url, database_key)
    store.save_sync(
        result["holdings"], result["operations"], result["history"], result["earn"]
    )
    return result

if st.button("Actualitzar ara", type="primary"):
    fetch_bitpanda_data.clear()
    st.rerun()

try:
    with st.spinner("Sincronitzant dades de Bitpanda..."):
        data = fetch_bitpanda_data(api_key, supabase_url, supabase_key)
except (BitpandaAPIError, BitpandaStoreError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

holdings = data["holdings"]
operations = data["operations"]
history = data["history"]
earn = data["earn"]

def money(value):
    try:
        return "€{:,.2f}".format(float(value))
    except (TypeError, ValueError):
        return "—"

def holding_value(row):
    value = row.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    return value if value is not None else row.get("valueEur") or row.get("value_eur")

total_value = 0.0
for item in holdings:
    try:
        total_value += float(holding_value(item) or 0)
    except (TypeError, ValueError):
        pass

latest_sync = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
st.caption("Última consulta UTC: " + latest_sync.strftime("%Y-%m-%d %H:%M:%S"))
c1, c2, c3, c4 = st.columns(4)
c1.metric("Valor de cartera", money(total_value))
c2.metric("Posicions", len(holdings))
c3.metric("Operacions importades", len(operations))
c4.metric("Productes Earn disponibles", len(earn))

tab_portfolio, tab_performance, tab_operations, tab_earn, tab_quality = st.tabs(
    ["Cartera", "Rendibilitat", "Operacions", "Earn", "Qualitat de dades"]
)

with tab_portfolio:
    if holdings:
        rows = []
        for item in holdings:
            asset = item.get("asset") if isinstance(item.get("asset"), dict) else {}
            rows.append({
                "Actiu": item.get("symbol") or asset.get("symbol") or item.get("name") or asset.get("name") or "—",
                "Quantitat": item.get("quantity") or item.get("amount"),
                "Valor EUR": holding_value(item),
                "Dades": item,
            })
        frame = pd.DataFrame(rows)
        st.dataframe(frame.drop(columns=["Dades"]), use_container_width=True, hide_index=True)
        frame["Valor EUR num"] = pd.to_numeric(frame["Valor EUR"], errors="coerce")
        chart = frame.dropna(subset=["Valor EUR num"])
        if not chart.empty:
            fig = px.pie(chart, names="Actiu", values="Valor EUR num", hole=.55,
                         title="Distribució de cartera")
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("L'API no ha retornat posicions per a aquest compte.")

with tab_performance:
    for timeframe in ("MONTH", "SIX_MONTH", "YEAR"):
        points = history.get(timeframe, [])
        if points:
            rows = []
            for point in points:
                value = point.get("value")
                if isinstance(value, dict):
                    value = value.get("value")
                rows.append({"Data": point.get("time") or point.get("timestamp"), "Valor EUR": value})
            frame = pd.DataFrame(rows)
            frame["Valor EUR"] = pd.to_numeric(frame["Valor EUR"], errors="coerce")
            frame = frame.dropna(subset=["Valor EUR"])
            if not frame.empty:
                st.markdown("#### " + timeframe.replace("_", " "))
                fig = px.line(frame, x="Data", y="Valor EUR", title="Evolució de cartera")
                fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Sense dades de rendibilitat per a " + timeframe + ".")

with tab_operations:
    if operations:
        rows = []
        for item in operations:
            rows.append({
                "Data": item.get("createdAt") or item.get("timestamp") or item.get("date"),
                "Tipus": item.get("type") or item.get("operationType"),
                "Actiu": item.get("symbol") or item.get("assetSymbol"),
                "Estat": item.get("status"),
                "ID": item.get("id") or item.get("operationId"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No s'han retornat operacions.")

with tab_earn:
    if earn:
        rows = [{
            "Actiu": item.get("symbol") or item.get("assetSymbol") or item.get("assetId"),
            "APR (%)": (item.get("annualPercentageRate") or item.get("annual_percentage_rate") or 0) * 100,
            "Tipus": item.get("type"), "Modalitat": item.get("mode"),
            "Disponible": item.get("enabled"), "Esgotat": item.get("soldout"),
        } for item in earn]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Són configuracions Earn disponibles, no necessàriament staking que ja tinguis contractat.")
    else:
        st.info("No hi ha configuracions Earn disponibles o el permís no està habilitat.")

with tab_quality:
    st.write({
        "font": "Bitpanda Public API v2",
        "observed_at": data["observed_at"],
        "holdings_rows": len(holdings),
        "operations_rows": len(operations),
        "earn_config_rows": len(earn),
        "history_timeframes": {key: len(value) for key, value in history.items()},
        "refresh_seconds": 900,
        "write_operations_enabled": False,
    })
    with st.expander("Resposta de diagnòstic (sense credencials)"):
        st.code(json.dumps({
            "holdings_sample": holdings[:2],
            "operation_sample": operations[:2],
            "earn_sample": earn[:2],
        }, ensure_ascii=False, indent=2, default=str))
