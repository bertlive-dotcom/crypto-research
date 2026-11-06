import json
import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone

from trading_desk import (
    Signal, evaluate_signal, new_portfolio, paper_entry, paper_exit,
    portfolio_summary, update_position_mark, update_position_from_candle, ensure_position_ids, STARTING_CAPITAL_USD,
)
from supabase_store import SupabasePaperStore, SupabaseStoreError
from scanner.store import ScannerStore, ScannerStoreError
from global_markets.crypto_feed import CryptoWatchlistFeed, BINANCE_SPOT_PAIRS
from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError
from global_markets.market_analysis import analyze_feed, analyze_candles, classify_entry_opportunity
from global_markets.alerts import build_technical_alerts
from global_markets.providers.financialdata import FinancialDataClient, FinancialDataError
from global_markets.providers.alphavantage import AlphaVantageClient, AlphaVantageError



def last_closed_candle(candles, now=None):
    """Return the newest fully closed candle, never the still-forming interval."""
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    closed = []
    for candle in candles:
        raw_close_time = candle.get("close_timestamp")
        if not raw_close_time:
            continue
        try:
            close_time = datetime.fromisoformat(str(raw_close_time).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        if close_time <= reference_time:
            closed.append((close_time, candle))
    return max(closed, key=lambda item: item[0])[1] if closed else None


def render_mid_cards(data, *args, **kwargs):
    """Render tabular records as responsive MIDMarkets cards (never an HTML table)."""
    if hasattr(data, "data") and isinstance(getattr(data, "data", None), pd.DataFrame):
        data = data.data
    frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if frame.empty:
        st.info("No hi ha registres disponibles.")
        return

    preferred_titles = (
        "Actiu", "Asset", "Symbol", "Parell", "Market", "asset", "symbol",
        "coin", "marginCoin", "Data", "Date", "event_type",
    )
    title_key = next((key for key in preferred_titles if key in frame.columns), frame.columns[0])
    records = frame.astype(object).where(pd.notna(frame), None).to_dict("records")

    for start in range(0, len(records), 2):
        card_columns = st.columns(2)
        for offset, record in enumerate(records[start:start + 2]):
            with card_columns[offset].container(border=True):
                title_value = record.get(title_key)
                st.markdown("**{}**".format(title_value if title_value not in (None, "") else "Registre"))
                details = [(key, value) for key, value in record.items() if key != title_key]
                for detail_start in range(0, len(details), 2):
                    detail_columns = st.columns(2)
                    for detail_offset, (label, value) in enumerate(details[detail_start:detail_start + 2]):
                        with detail_columns[detail_offset]:
                            st.caption(str(label))
                            if value is None or value == "":
                                display_value = "—"
                            elif isinstance(value, (dict, list, tuple)):
                                display_value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                            elif isinstance(value, float):
                                display_value = "{:,.4f}".format(value).rstrip("0").rstrip(".")
                            else:
                                display_value = str(value)
                            st.write(display_value)

st.set_page_config(page_title="MIDMarkets | Markets Intelligence Desk", layout="wide")

# MIDMarkets visual identity: navy / electric blue / cyan, with restrained
# green and red market states. Presentation only; no data or trading logic.
st.markdown("""
<style>
:root {
  --mid-bg: #050d19;
  --mid-panel: #091a2c;
  --mid-panel-2: #0c2238;
  --mid-blue: #0878d1;
  --mid-cyan: #19c8ff;
  --mid-text: #f4f8fc;
  --mid-muted: #91a8bd;
  --mid-green: #00b879;
  --mid-red: #e3484d;
}
.stApp, [data-testid="stAppViewContainer"] {
  background: radial-gradient(ellipse at 78% 0%, #092b49 0%, var(--mid-bg) 44%);
  color: var(--mid-text);
}
[data-testid="stHeader"] { background: rgba(5,13,25,.88); }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #07182a, #040b14);
  border-right: 1px solid rgba(25,200,255,.22);
}
.block-container { padding-top: 1.35rem; padding-bottom: 2.5rem; max-width: 1600px; }
h1, h2, h3, h4 { color: var(--mid-text) !important; letter-spacing: -.025em; }
p, label, [data-testid="stCaptionContainer"] { color: var(--mid-muted); }
[data-testid="stMetric"] {
  background: linear-gradient(145deg, rgba(12,34,56,.96), rgba(6,20,35,.96));
  border: 1px solid rgba(25,200,255,.45);
  border-radius: 14px;
  padding: 16px 18px;
  box-shadow: 0 0 22px rgba(0,130,220,.08);
}
[data-testid="stMetricLabel"] { color: #a8c5dc !important; }
[data-testid="stMetricValue"] { color: #f7fbff !important; }
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap: .35rem; border-bottom: 1px solid rgba(25,200,255,.28);
  overflow-x: auto; flex-wrap: nowrap; scrollbar-width: thin;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
  flex: 0 0 auto; white-space: nowrap; min-width: max-content;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: var(--mid-cyan); }
[data-testid="stTabs"] [data-baseweb="tab-border"] { background: rgba(25,200,255,.25); }
[data-testid="stMarkdownContainer"] p,
[data-testid="stCaptionContainer"] p,
[data-testid="stWidgetLabel"] p { color: #b7c9da !important; }
[data-testid="stVerticalBlock"] > [style*="gap"] { gap: .8rem; }
[data-testid="stTabs"] button[role="tab"] {
  color: #9bb3c8; border-radius: 9px 9px 0 0;
}
[data-testid="stTabs"] button[aria-selected="true"] {
  color: #fff; border-bottom: 3px solid var(--mid-cyan);
  background: rgba(8,120,209,.13);
}
.stButton > button, [data-testid="stDownloadButton"] button {
  border: 1px solid var(--mid-cyan);
  border-radius: 9px;
  background: linear-gradient(110deg, #075b9d, #087fc7);
  color: white; font-weight: 650;
}
.stButton > button:hover { border-color: #8ce8ff; color: white; box-shadow: 0 0 16px rgba(25,200,255,.25); }
[data-testid="stDataFrame"], [data-testid="stTable"] {
  border: 1px solid rgba(25,200,255,.28); border-radius: 10px; overflow: hidden;
}
[data-testid="stExpander"] {
  border: 1px solid rgba(25,200,255,.24); border-radius: 12px;
  background: rgba(8,26,44,.55);
}
[data-testid="stAlert"] { border-radius: 10px; }
.mid-brand {
  display:flex; align-items:center; gap:16px; flex-wrap:wrap;
  padding: 18px 22px; margin: 0 0 18px 0;
  border: 1px solid rgba(25,200,255,.55); border-radius: 16px;
  background: linear-gradient(105deg, rgba(5,20,37,.98), rgba(5,52,88,.82));
  box-shadow: 0 0 28px rgba(0,145,230,.12), inset 0 1px rgba(255,255,255,.05);
}
.mid-logo { font-size: clamp(2rem, 4vw, 3.2rem); font-weight: 850; letter-spacing: -.06em; color: #fff; }
.mid-divider { width: 3px; height: 48px; background: var(--mid-cyan); box-shadow: 0 0 12px var(--mid-cyan); }
.mid-brand-title { font-size: clamp(1.1rem, 2vw, 1.65rem); font-weight: 750; line-height: 1.1; color: #fff; }
.mid-brand-sub { margin-top: 5px; color: #a9c9e2; font-size: .88rem; letter-spacing: .08em; text-transform: uppercase; }
.mid-tagline { margin-left:auto; color:#b8eaff; font-size:.78rem; letter-spacing:.16em; font-weight:700; }
@media (max-width: 640px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; }
  .mid-brand { padding: 14px; gap: 10px; }
  .mid-divider { height: 38px; }
  .mid-tagline { width:100%; margin-left:0; font-size:.68rem; }
  [data-testid="stMetric"] { padding: 12px; }
}
</style>
<div class="mid-brand">
  <div class="mid-logo">MID</div>
  <div class="mid-divider"></div>
  <div>
    <div class="mid-brand-title">Markets Intelligence Desk</div>
    <div class="mid-brand-sub">Independent research across global markets</div>
  </div>
  <div class="mid-tagline">DATA · SIGNALS · INTELLIGENCE</div>
</div>
""", unsafe_allow_html=True)

def secret(key):
    try:
        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""

password = secret("DASHBOARD_PASSWORD")
if not password:
    st.error("Set DASHBOARD_PASSWORD, CMC_API_KEY and TWELVE_DATA_API_KEY in hosting Secrets.")
    st.stop()
if st.text_input("Password", type="password") != password:
    st.stop()

cmc_key = secret("CMC_API_KEY")
twelve_key = secret("TWELVE_DATA_API_KEY")
if not cmc_key or not twelve_key:
    st.error("Missing API keys in hosting Secrets.")
    st.stop()

# Crypto market data and paper-position marks refresh every minute. Keep equity
# quotes on a slower cache so the Twelve Data credit budget is not consumed rapidly.
st_autorefresh(interval=60_000, limit=None, key="market-data-auto-refresh")
st.caption("Crypto market data and paper-position marks refresh every 60 seconds. Stock and ETF quotes refresh hourly in one batched Twelve Data request; credits are still counted per symbol.")

supabase_url = secret("SUPABASE_URL")
supabase_service_key = secret("SUPABASE_SERVICE_ROLE_KEY")
paper_store = None
if supabase_url and supabase_service_key:
    try:
        paper_store = SupabasePaperStore(supabase_url, supabase_service_key)
    except ValueError as error:
        st.error("Supabase configuration error: " + str(error))
        st.stop()

@st.cache_data(ttl=55)
def get_crypto(key):
    response = requests.get(
        "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
        headers={"X-CMC_PRO_API_KEY": key},
        params={"symbol": "BTC,ETH,SOL,LINK,XLM,SUI,HYPE", "convert": "USD"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status", {}).get("error_code", 0):
        raise RuntimeError(data.get("status", {}).get("error_message", "CMC error"))
    rows = []
    for symbol in ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"]:
        value = data.get("data", {}).get(symbol, [])
        if isinstance(value, dict):
            value = [value]
        quote = value[0].get("quote", {}).get("USD", {}) if value else {}
        rows.append({
            "Asset": symbol, "Price USD": quote.get("price"),
            "24h %": quote.get("percent_change_24h"),
            "1h %": quote.get("percent_change_1h"),
            "24h Volume USD": quote.get("volume_24h"),
            "Updated": quote.get("last_updated"), "Source": "CoinMarketCap",
        })
    return rows

@st.cache_data(ttl=3600)
def get_quotes(symbols, key):
    symbols = tuple(dict.fromkeys(symbols))
    if not symbols:
        return {}

    def errors(message):
        return {symbol: {"_error": message} for symbol in symbols}

    def provider_error(code):
        code = str(code or "")
        if code == "429":
            return "S'ha assolit el límit de Twelve Data. Espera que es restableixi la quota o revisa el consum del compte."
        if code == "401":
            return "La clau API de Twelve Data no és vàlida."
        if code == "403":
            return "El pla de Twelve Data no permet aquesta consulta."
        return f"Twelve Data no ha pogut retornar dades (codi {code or 'desconegut'})."

    try:
        response = requests.get(
            "https://api.twelvedata.com/quote",
            params={"symbol": ",".join(symbols)},
            headers={"Authorization": f"apikey {key}"},
            timeout=20,
        )
    except requests.RequestException:
        return errors("No s'ha pogut connectar amb Twelve Data.")

    if not response.ok:
        return errors(provider_error(response.status_code))
    try:
        batch_data = response.json()
    except ValueError:
        return errors("Twelve Data ha retornat dades no vàlides.")

    if isinstance(batch_data, dict) and (
        batch_data.get("status") == "error" or "code" in batch_data
    ):
        return errors(provider_error(batch_data.get("code")))

    if isinstance(batch_data, list):
        quote_map = {
            str(item.get("symbol", "")).upper(): item
            for item in batch_data if isinstance(item, dict)
        }
    elif isinstance(batch_data, dict) and batch_data.get("symbol"):
        quote_map = {str(batch_data["symbol"]).upper(): batch_data}
    elif isinstance(batch_data, dict):
        quote_map = {str(symbol).upper(): quote for symbol, quote in batch_data.items()}
    else:
        return errors("Twelve Data ha retornat dades no vàlides.")

    results = {}
    for symbol in symbols:
        quote = quote_map.get(symbol.upper())
        if not isinstance(quote, dict):
            results[symbol] = {"_error": "Twelve Data no ha retornat dades per a aquest símbol."}
            continue
        if quote.get("status") == "error" or "code" in quote:
            results[symbol] = {"_error": provider_error(quote.get("code"))}
            continue
        price = quote.get("close") or quote.get("price")
        try:
            results[symbol] = {
                "Asset": symbol,
                "Price USD": float(price) if price else None,
                "24h %": float(quote["percent_change"]) if quote.get("percent_change") else None,
                "Updated": quote.get("datetime"),
                "Source": "Twelve Data",
            }
        except (TypeError, ValueError, KeyError):
            results[symbol] = {"_error": "Twelve Data ha retornat dades no vàlides."}
    return results

if st.button("Refresh crypto market data"):
    get_crypto.clear()

@st.cache_data(ttl=300)
def get_global_crypto_analysis():
    feed = CryptoWatchlistFeed()
    raw = feed.fetch(intervals=("1d", "4h"), limit=200)
    return analyze_feed(raw)

@st.cache_data(ttl=900)
def get_global_daily_asset_analysis(api_key):
    client = FinancialDataClient(api_key, max_retries=1, max_pages=2)
    seeds = {
        "equity": [("NVDA", False), ("TSM", False), ("ASML", False),
                   ("MSFT", False), ("GOOGL", False), ("AMZN", False),
                   ("AVGO", False), ("SU.PA", True)],
        "etf": [(symbol, False) for symbol in ["SPY", "QQQ", "VT", "IWDA", "EEM"]],
        "commodity": [(symbol, False) for symbol in ["GC", "SI", "CL", "BZ", "HG", "NG"]],
    }
    analyses, unavailable, quality = [], [], []
    for asset_class, instruments in seeds.items():
        for symbol, international in instruments:
            try:
                feed = client.fetch_daily_prices_with_quality(
                    symbol, asset_class, international=international, limit=120
                )
                rows = feed["candles"]
                result = analyze_candles(rows, max_age_seconds=5 * 86400)
                result["asset_class"] = asset_class
                result["symbol"] = symbol
                result["source_records"] = feed["source_records"]
                result["valid_records"] = len(rows)
                result["rejected_records"] = len(feed["rejected_records"])
                analyses.append(result)
                if feed["rejected_records"]:
                    quality.append({
                        "asset_class": asset_class, "symbol": symbol,
                        "rejected_records": len(feed["rejected_records"]),
                        "examples": "; ".join(
                            f'{item["date"]}: {item["reason"]}'
                            for item in feed["rejected_records"][:3]
                        ),
                    })
            except (FinancialDataError, ValueError) as error:
                unavailable.append({
                    "asset_class": asset_class, "symbol": symbol,
                    "reason": str(error),
                })
    return {
        "source": "FinancialData.Net", "observed_at": datetime.now(timezone.utc).isoformat(),
        "analyses": analyses, "unavailable": unavailable, "quality": quality,
    }


@st.cache_data(ttl=900)
def get_global_fx_analysis(api_key):
    client = AlphaVantageClient(api_key)
    pairs = [("EUR", "USD"), ("USD", "JPY"), ("GBP", "USD"), ("USD", "CHF")]
    analyses, unavailable = [], []
    for index, (base, quote) in enumerate(pairs):
        symbol = base + quote
        try:
            rows = client.get_fx_daily(base, quote)
            result = analyze_candles(rows, max_age_seconds=5 * 86400)
            result["asset_class"] = "forex"
            result["symbol"] = symbol
            result["volume_available"] = False
            analyses.append(result)
        except (AlphaVantageError, ValueError) as error:
            unavailable.append({"asset_class": "forex", "symbol": symbol, "reason": str(error)})
            if error.__class__.__name__ == "AlphaVantageRateLimitError" or "rate limit" in str(error).lower():
                for remaining_base, remaining_quote in pairs[index + 1:]:
                    unavailable.append({
                        "asset_class": "forex",
                        "symbol": remaining_base + remaining_quote,
                        "reason": "Skipped to preserve provider quota after rate-limit response",
                    })
                break
    return {
        "source": "Alpha Vantage FX_DAILY", "observed_at": datetime.now(timezone.utc).isoformat(),
        "analyses": analyses, "unavailable": unavailable,
    }


@st.cache_data(ttl=300)
def get_cross_market_report(api_key):
    from global_markets.cross_market import analyze_cross_market, fetch_cross_market_candles
    feed = fetch_cross_market_candles(api_key)
    report = analyze_cross_market(feed["candles"])
    report["provider_unavailable"] = feed["unavailable"]
    report["feed_observed_at"] = feed["observed_at"]
    return report


latest_crypto_prices = {}
latest_crypto_market_data = {}
market_tab, desk_tab, global_tab, scanner_tab, cross_market_tab, bitunix_tab = st.tabs([
    "Market dashboard", "AI Crypto Trading Desk", "Global opportunity scanner", "Market Scanner",
    "Cross-market risk", "Bitunix (read-only)"
])
with market_tab:
    st.caption("Checked at " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    st.subheader("Crypto - CoinMarketCap")
    try:
        crypto_rows = get_crypto(cmc_key)
        latest_crypto_market_data = {row["Asset"]: row for row in crypto_rows}
        latest_crypto_prices = {row["Asset"]: row["Price USD"] for row in crypto_rows if row.get("Price USD")}
        crypto_chart_rows = [
            {"Asset": row["Asset"], "24h change (%)": row.get("24h %")}
            for row in crypto_rows if row.get("24h %") is not None
        ]
        if crypto_chart_rows:
            st.markdown("#### Crypto market performance · 24h")
            crypto_fig = px.bar(pd.DataFrame(crypto_chart_rows), x="Asset", y="24h change (%)", color="24h change (%)", color_continuous_scale=["#e3484d", "#091a2c", "#00b879"], title="Canvi 24h · passa el cursor per veure valors")
            crypto_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", coloraxis_showscale=False, height=360, margin=dict(l=8,r=8,t=55,b=8), dragmode="zoom")
            st.plotly_chart(crypto_fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
        with st.expander("Detailed crypto quotes", expanded=False):
            render_mid_cards(pd.DataFrame(crypto_rows), width="stretch", hide_index=True)
    except Exception as error:
        st.error("CMC request failed: " + str(error))
    st.subheader("Stocks and ETFs - Twelve Data")
    symbols = st.multiselect(
        "Symbols",
        ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "SPY", "QQQ"],
        ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
        max_selections=6,
        help="Limitat a 6 símbols per mantenir baix el consum de crèdits de Twelve Data.",
    )
    try:
        quote_results = get_quotes(tuple(symbols), twelve_key)
    except Exception:
        quote_results = {
            symbol: {"_error": "No s'ha pogut actualitzar la cotització de Twelve Data."}
            for symbol in symbols
        }
    rows = []
    for symbol in symbols:
        quote_result = quote_results.get(
            symbol, {"_error": "Twelve Data no ha retornat dades per a aquest símbol."}
        )
        if "_error" in quote_result:
            st.warning(symbol + ": " + quote_result["_error"])
        else:
            rows.append(quote_result)
    if rows:
        stock_chart_rows = [
            {"Symbol": row["Asset"], "24h change (%)": row.get("24h %")}
            for row in rows if row.get("24h %") is not None
        ]
        if stock_chart_rows:
            st.markdown("#### Equity & ETF performance · provider period")
            stock_fig = px.bar(pd.DataFrame(stock_chart_rows), x="Symbol", y="24h change (%)", color="24h change (%)", color_continuous_scale=["#e3484d", "#091a2c", "#00b879"], title="Variació del període del proveïdor")
            stock_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", coloraxis_showscale=False, height=340, margin=dict(l=8,r=8,t=55,b=8), dragmode="zoom")
            st.plotly_chart(stock_fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
        with st.expander("Detailed equity and ETF quotes", expanded=False):
            render_mid_cards(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("Informational market snapshots only. No trade execution.")

with desk_tab:
    st.subheader("Paper Trading - virtual capital")
    st.warning("SIMULATION ONLY. No exchange orders, wallet connections, or real funds are used.")
    if "paper_portfolio" not in st.session_state:
        if paper_store:
            try:
                saved_state = paper_store.load_state()
                st.session_state.paper_portfolio = saved_state or new_portfolio(STARTING_CAPITAL_USD)
                if saved_state is None:
                    paper_store.save_state(st.session_state.paper_portfolio, {"event_type": "portfolio_initialized", "asset": "", "starting_capital_usd": STARTING_CAPITAL_USD})
            except SupabaseStoreError as error:
                st.error("Persistent paper ledger unavailable: " + str(error))
                st.stop()
        else:
            st.session_state.paper_portfolio = new_portfolio(STARTING_CAPITAL_USD)
    if "desk_last_result" not in st.session_state:
        st.session_state.desk_last_result = None

    portfolio = st.session_state.paper_portfolio
    if ensure_position_ids(portfolio) and paper_store:
        try:
            paper_store.save_state(portfolio, {"event_type": "position_ids_migrated", "asset": "", "position_count": len(portfolio["open_positions"])})
        except SupabaseStoreError as error:
            st.error("Could not persist position ID migration: " + str(error))
            st.stop()
    if not paper_store:
        st.warning("Supabase is not configured: this session is temporary and will not provide a durable 30-day journal. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Streamlit Secrets.")
    else:
        st.caption("Persistent paper ledger connected to Supabase.")
    # Runs every 60 seconds; candle extremes detect TP/SL touches between quote updates.
    candle_client = BinanceMarketDataClient()
    for open_position in list(portfolio["open_positions"]):
        asset = open_position["asset"].upper()
        pair = BINANCE_SPOT_PAIRS.get(asset + "USD")
        stopped_trade = None
        market_event = None
        if pair:
            try:
                candles = candle_client.get_klines(pair, interval="1m", limit=2)
                candle = last_closed_candle(candles)
                if candle is not None:
                    candle_stamp = candle["timestamp"]
                if candle is not None and open_position.get("last_market_candle_timestamp") != candle_stamp:
                    stopped_trade = update_position_from_candle(portfolio, asset, high=float(candle["high"]), low=float(candle["low"]), close=float(candle["close"]), position_id=open_position["position_id"])
                    if not stopped_trade:
                        open_position["last_market_candle_timestamp"] = candle_stamp
                    market_event = {"event_type": stopped_trade["exit_reason"] if stopped_trade else "market_candle_mark", "asset": asset, "position_id": open_position["position_id"], "price_usd": float(candle["close"]), "candle_timestamp": candle_stamp, "candle_high": float(candle["high"]), "candle_low": float(candle["low"]), "trade": stopped_trade}
            except (BinanceMarketDataError, ValueError, KeyError, TypeError) as error:
                st.warning("Binance candle check unavailable for {}: {}. Falling back to latest CMC quote.".format(asset, error))
        if market_event is None and not stopped_trade:
            current_price = latest_crypto_prices.get(asset)
            if current_price and abs(float(current_price) - float(open_position["last_price_usd"])) > 1e-12:
                stopped_trade = update_position_mark(portfolio, asset, float(current_price), position_id=open_position["position_id"])
                market_event = {"event_type": stopped_trade["exit_reason"] if stopped_trade else "market_mark", "asset": asset, "position_id": open_position["position_id"], "price_usd": float(current_price), "trade": stopped_trade}
        if market_event and paper_store:
            try:
                paper_store.save_state(portfolio, market_event)
            except SupabaseStoreError as error:
                st.error("Could not persist market update: " + str(error))
                st.stop()
        if stopped_trade:
            st.warning("Automatic {} triggered for {} at simulated level.".format(stopped_trade["exit_reason"].replace("_", " "), asset))

    summary = portfolio_summary(portfolio)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Virtual equity", "USD {:.2f}".format(summary["equity_usd"]))
    col2.metric("Cash available", "USD {:.2f}".format(summary["cash_usd"]))
    col3.metric("Realized P&L", "USD {:.2f}".format(summary["realized_pnl_usd"]))
    col4.metric("Unrealized P&L", "USD {:.2f}".format(summary["unrealized_pnl_usd"]))
    st.caption("Starting capital: USD {:.2f} | Return: {:.2f}% | Open: {} | Closed: {}".format(
        portfolio["starting_capital"], summary["total_return_pct"],
        summary["open_positions"], summary["closed_trades"]))
    st.markdown("#### Paper portfolio performance")
    pnl_chart = pd.DataFrame([
        {"Component": "Realized P&L", "USD": summary["realized_pnl_usd"]},
        {"Component": "Unrealized P&L", "USD": summary["unrealized_pnl_usd"]},
    ]).set_index("Component")
    pnl_fig = px.bar(pnl_chart.reset_index(), x="Component", y="USD", color="Component", color_discrete_sequence=["#19c8ff", "#0878d1"], title="Resultat de la cartera simulada")
    pnl_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, height=300, margin=dict(l=8,r=8,t=50,b=8))
    st.plotly_chart(pnl_fig, use_container_width=True, config={"displaylogo": False})
    st.caption("P&L components are current portfolio snapshots, not a historical equity curve.")

    st.markdown("#### Five-agent pipeline")
    st.write("Scout: signal intake -> Filter: hard rules -> Analyst: risk review -> Sniper: simulated entry -> Guard: automatic stop-loss, take-profit and exposure controls.")
    st.caption("First increment: candidates and Solana on-chain metrics are entered manually. The 640-wallet scanner and automated holder/bundle analytics are not connected.")

    direction = st.selectbox("Direction", ["long", "short"], format_func=lambda value: "Long (profit if price rises)" if value == "long" else "Short (profit if price falls)")
    market = st.selectbox("Market", ["major", "solana"],
        format_func=lambda value: "BTC / ETH / major altcoins" if value == "major" else "Solana tokens / memecoins")
    if market == "major":
        asset = st.selectbox("Asset", ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"])
        market_snapshot = latest_crypto_market_data.get(asset, {})
        price = market_snapshot.get("Price USD")
        volume = market_snapshot.get("24h Volume USD")
        gain1h = market_snapshot.get("1h %")
        quote_updated = market_snapshot.get("Updated")
        quote_is_fresh = False
        quote_age_seconds = None
        if quote_updated:
            try:
                quote_time = datetime.fromisoformat(str(quote_updated).replace("Z", "+00:00"))
                if quote_time.tzinfo is None:
                    quote_time = quote_time.replace(tzinfo=timezone.utc)
                quote_age_seconds = (datetime.now(timezone.utc) - quote_time.astimezone(timezone.utc)).total_seconds()
                quote_is_fresh = 0 <= quote_age_seconds <= 300
            except (TypeError, ValueError):
                quote_is_fresh = False
        if price is not None and float(price) > 0:
            st.metric("CoinMarketCap reference price (USD)", "{:,.8f}".format(float(price)))
        else:
            st.error("No valid live CoinMarketCap price is available for this asset.")
        data_col1, data_col2 = st.columns(2)
        data_col1.metric("24h volume (CoinMarketCap)", "{:,.0f} USD".format(float(volume)) if volume is not None else "Unavailable")
        data_col2.metric("CoinMarketCap change (1h)", "{:+.2f}%".format(float(gain1h)) if gain1h is not None else "Unavailable")
        st.caption("These filters use CoinMarketCap's 24h volume and 1h price-change fields. Quote timestamp: {}{}".format(
            quote_updated or "unavailable",
            " · age {:.0f} sec".format(quote_age_seconds) if quote_age_seconds is not None else ""))
        if not quote_is_fresh:
            st.error("CoinMarketCap quote is missing or older than 5 minutes. Refresh market data before simulating an entry.")
        if volume is None or gain1h is None:
            st.error("The quote is missing 24h volume or 1h price change; the paper signal cannot pass.")
        gain45 = None
    else:
        asset = st.text_input("Token symbol or identifier", placeholder="e.g. TOKEN")
        price = st.number_input("Reference price (USD)", min_value=0.00000001, value=None, format="%.8f", required=True)
        liquidity = st.number_input("Liquidity (USD)", min_value=0.0, value=None, step=1000.0, required=True)
        top10 = st.number_input("Top-10 holder concentration (%)", min_value=0.0, max_value=100.0, value=None, required=True)
        dev = st.number_input("Developer wallet share (%)", min_value=0.0, max_value=100.0, value=None, required=True)
        bundled = st.selectbox("Bundled buys in first 60 seconds?", [None, False, True],
            format_func=lambda value: "Select one" if value is None else "Yes" if value else "No")
        gain45 = st.number_input("Price change in last 45 minutes (%)", min_value=-100.0, max_value=1000.0, value=None, required=True)
        source_sold = st.selectbox("Source wallet already sold?", [None, False, True],
            format_func=lambda value: "Select one" if value is None else "Yes" if value else "No")
        solana_metrics_source = st.text_input("Source for on-chain metrics", placeholder="Explorer or data provider")
        solana_metrics_as_of = st.text_input("Metrics observed at (UTC)", placeholder="YYYY-MM-DD HH:MM")
        st.caption("Solana metrics are not connected to an automatic provider. Leave a field blank rather than guessing; an entry stays disabled until each value and its source/time are supplied.")
        volume = None
        gain1h = None
        quote_updated = None
        quote_is_fresh = False

    entry_fill_preview = (float(price) * (1.0 + 0.003 if direction == "long" else 1.0 - 0.003)) if price and float(price) > 0 else None
    stop_col, stop_price_col = st.columns([2, 1])
    with stop_col:
        stop_pct = st.slider("Stop Loss (%)", min_value=1, max_value=30, value=10, key=f"stop_{market}_{asset}")
    with stop_price_col:
        stop_preview = (entry_fill_preview * (1.0 - stop_pct / 100.0 if direction == "long" else 1.0 + stop_pct / 100.0)) if entry_fill_preview else None
        st.metric("Preu Stop Loss", f"${stop_preview:,.8f}" if stop_preview else "—")

    tp_col, tp_price_col = st.columns([2, 1])
    with tp_col:
        take_profit_pct = st.slider("Take Profit (%)", min_value=1, max_value=100, value=20, key=f"tp_{market}_{asset}")
    with tp_price_col:
        take_profit_preview = (entry_fill_preview * (1.0 + take_profit_pct / 100.0 if direction == "long" else 1.0 - take_profit_pct / 100.0)) if entry_fill_preview else None
        st.metric("Preu Take Profit", f"${take_profit_preview:,.8f}" if take_profit_preview else "—")

    if market == "major":
        entry_inputs_ready = (
            price is not None and float(price) > 0
            and volume is not None and gain1h is not None and quote_is_fresh
        )
    else:
        entry_inputs_ready = (
            bool(asset.strip()) and price is not None and float(price) > 0
            and all(value is not None for value in (
                liquidity, top10, dev, bundled, gain45, source_sold
            ))
            and bool(solana_metrics_source.strip()) and bool(solana_metrics_as_of.strip())
        )
    submitted = st.button("Run filters and simulate entry", disabled=not entry_inputs_ready)
    if submitted:
        if market == "major":
            signal = Signal(asset=asset, market=market, price_usd=float(price),
                volume_24h_usd=volume, gain_1h_pct=gain1h,
                source="CoinMarketCap live quote as of {}".format(quote_updated))
        else:
            signal = Signal(asset=asset, market=market, price_usd=price,
                liquidity_usd=liquidity, top10_holder_pct=top10, dev_wallet_pct=dev,
                bundled_buys_first_60s=bundled, gain_45m_pct=gain45,
                source_wallet_sold=source_sold,
                source="manual on-chain metrics from {} as of {}".format(
                    solana_metrics_source.strip(), solana_metrics_as_of.strip()))

    if submitted:
        result = evaluate_signal(signal)
        st.session_state.desk_last_result = {"signal": signal, "result": result}
        if result["approved"]:
            try:
                position = paper_entry(portfolio, signal, stop_loss_pct=float(stop_pct), take_profit_pct=float(take_profit_pct), direction=direction)
                if paper_store:
                    paper_store.save_state(portfolio, {"event_type": "entry", "asset": signal.asset, "signal": signal.__dict__, "position": position})
                st.success("Signal approved. Paper position: USD {:.2f}; stop price {:.8f}; take-profit price {:.8f}.".format(
                    position["notional_usd"], position["stop_price"], position["take_profit_price"]))
            except ValueError as error:
                st.error(str(error))
        else:
            st.error("Signal rejected. No paper position opened.")

    last = st.session_state.desk_last_result
    if last:
        st.markdown("#### Latest filter result")
        status = "APPROVED" if last["result"]["approved"] else "REJECTED"
        st.write("{} | {} | {}".format(last["signal"].asset, last["signal"].market, status))
        for reason in last["result"]["reasons"]:
            st.write("- " + reason)
        if not last["result"]["reasons"]:
            st.write("All applicable checks passed.")

    st.markdown("#### Open paper positions")
    if portfolio["open_positions"]:
        render_mid_cards(pd.DataFrame(portfolio["open_positions"]), width="stretch", hide_index=True)
        with st.form("position_update_form"):
            position_by_id = {position["position_id"]: position for position in portfolio["open_positions"]}
            selected_id = st.selectbox(
                "Position",
                list(position_by_id),
                format_func=lambda position_id: "{} · {} · {}".format(
                    position_by_id[position_id]["asset"],
                    position_by_id[position_id].get("direction", "long").upper(),
                    position_id[:8],
                ),
            )
            selected_position = position_by_id[selected_id]
            selected_asset = selected_position["asset"]
            default_price = selected_position["last_price_usd"]
            mark_price = st.number_input("Latest/reference price (USD)", min_value=0.00000001, value=float(default_price), format="%.8f")
            update_mark = st.form_submit_button("Update simulated market price")
            close_position = st.form_submit_button("Close paper position at this price")
        if update_mark:
            stopped_trade = update_position_mark(portfolio, selected_asset, mark_price, position_id=selected_id)
            if paper_store:
                paper_store.save_state(portfolio, {"event_type": stopped_trade["exit_reason"] if stopped_trade else "manual_mark", "asset": selected_asset, "position_id": selected_id, "price_usd": mark_price, "trade": stopped_trade})
            if stopped_trade:
                st.warning("Automatic {} triggered. Simulated exit P&L: USD {:.2f}".format(stopped_trade["exit_reason"].replace("_", " "), stopped_trade["realized_pnl_usd"]))
            else:
                st.success("Paper mark price updated.")
        if close_position:
            trade = paper_exit(portfolio, selected_asset, mark_price, position_id=selected_id)
            if paper_store:
                paper_store.save_state(portfolio, {"event_type": "manual_exit", "asset": selected_asset, "position_id": selected_id, "trade": trade})
            st.success("Paper position closed. Realized P&L: USD {:.2f}".format(trade["realized_pnl_usd"]))
    else:
        st.info("No open paper positions.")

    st.markdown("#### Closed paper trades")
    if portfolio["closed_trades"]:
        render_mid_cards(pd.DataFrame(portfolio["closed_trades"]), width="stretch", hide_index=True)
    else:
        st.caption("No closed trades yet.")

    st.caption("Long/short simulation enabled. Risk defaults: 1% cash risk budget per trade, 10% stop-loss, 20% take-profit, max 10% position size, max 25% aggregate open exposure, 0.10% fee and 0.30% adverse slippage per side.")
    if paper_store:
        st.markdown("#### 30-day paper-trading journal")
        try:
            recent_events = paper_store.load_events(days=30)
            if recent_events:
                # Supabase JSONB payloads have different shapes and value types per
                # event. Keep each payload as readable JSON so Arrow does not infer
                # an inconsistent nested schema when rendering the journal.
                display_events = [
                    {
                        **event,
                        "payload": json.dumps(event.get("payload"), ensure_ascii=False, sort_keys=True)
                        if event.get("payload") is not None
                        else None,
                    }
                    for event in recent_events
                ]
                render_mid_cards(pd.DataFrame(display_events), width="stretch", hide_index=True)
            else:
                st.caption("No ledger events in the last 30 days yet.")
        except SupabaseStoreError as error:
            st.warning("Could not load journal history: " + str(error))
    if st.button("Reset virtual portfolio to USD 80"):
        st.session_state.paper_portfolio = new_portfolio(STARTING_CAPITAL_USD)
        if paper_store:
            paper_store.save_state(st.session_state.paper_portfolio, {"event_type": "portfolio_reset", "asset": "", "starting_capital_usd": STARTING_CAPITAL_USD})
        st.session_state.desk_last_result = None
        st.rerun()



with global_tab:
    st.subheader("Global opportunity scanner - crypto watchlist")
    st.caption("Binance public spot data · read-only · 4h and daily analysis · independent from the existing Market Scanner.")
    st.warning("Research and technical screening only. This view does not open, close or modify paper positions.")
    if st.button("Fetch and analyse global crypto watchlist", key="run_global_crypto_scan"):
        get_global_crypto_analysis.clear()
        st.session_state["global_crypto_scan_requested"] = True

    if st.session_state.get("global_crypto_scan_requested"):
        try:
            with st.spinner("Fetching public candles and calculating indicators..."):
                global_report = get_global_crypto_analysis()
            analyses = global_report["analyses"]
            eligible = [row for row in analyses if row["eligible"]]
            rejected = [row for row in analyses if not row["eligible"]]
            unavailable_items = global_report["provider_unavailable"]
            preflight_reasons = {
                "pair_not_listed_on_binance_spot",
                "pair_not_trading_on_binance_spot",
                "spot_trading_not_allowed_for_pair",
                "no_binance_pair_mapping",
                "spot_listing_check_failed",
            }
            preflight_items = [item for item in unavailable_items if item.get("reason") in preflight_reasons]
            request_failures = [item for item in unavailable_items if item.get("reason") not in preflight_reasons]
            skipped_symbols = {item.get("symbol") for item in preflight_items if item.get("symbol")}
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Valid series", global_report["eligible_series"])
            c2.metric("Rejected series (data quality)", global_report["rejected_series"])
            c3.metric("Symbols with valid data", len({row["symbol"] for row in eligible}))
            c4.metric("Assets skipped at Binance preflight", len(skipped_symbols))
            st.caption("Rejected series are returned candles that failed data-quality checks. The Binance Spot catalog is checked before candle retrieval; assets missing, inactive, or not allowed for Spot are skipped without requesting candles. Provider request failures are shown separately.")
            st.caption("Data source: {} | Feed timestamp: {}".format(
                global_report.get("source"), global_report.get("observed_at")))

            freshness_status_labels = {
                "current": "Actual",
                "stale": "Endarrerida",
                "insufficient_history": "Historial insuficient",
                "unavailable": "No disponible",
                "rejected": "Dades rebutjades",
            }
            freshness_reason_labels = {
                "stale_market_data": "Espelma tancada més antiga que el llindar admès",
                "insufficient_history": "No hi ha prou espelmes tancades per calcular els indicadors",
                "no_candles": "El proveïdor no ha retornat espelmes",
                "no_closed_candles": "Encara no hi ha espelmes tancades",
                "pair_not_listed_on_binance_spot": "Parell absent del catàleg Binance Spot",
                "pair_not_trading_on_binance_spot": "Parell Binance Spot inactiu",
                "spot_trading_not_allowed_for_pair": "Spot no permès per a aquest parell",
                "no_binance_pair_mapping": "Sense equivalència configurada amb Binance",
                "spot_listing_check_failed": "No s'ha pogut verificar el catàleg Spot",
                "rate_limit": "Límit de consultes assolit",
                "provider_request_failed": "Ha fallat la petició al proveïdor",
                "invalid_provider_response": "Resposta invàlida del proveïdor",
                "provider_error": "Error del proveïdor de dades",
                "malformed_candle_data": "Dades d'espelma invàlides",
                "unsupported_interval": "Interval no admès",
                "mixed_symbol_or_interval": "Símbols o intervals barrejats",
                "future_candle": "Espelma amb data futura",
                "invalid_close_price": "Preu de tancament invàlid",
                "unknown": "Motiu no especificat pel proveïdor",
            }
            freshness_rows = [{
                "Actiu": str(item.get("symbol") or "—").replace("USDT", "").replace("USD", ""),
                "Interval": item.get("interval") or "—",
                "Última espelma tancada UTC": item.get("latest_candle_close") or "—",
                "Antiguitat (h)": round(item["age_seconds"] / 3600, 1) if item.get("age_seconds") is not None else None,
                "Espelmes": item.get("bars") if item.get("bars") is not None else None,
                "Estat": freshness_status_labels.get(item.get("status"), item.get("status", "—")),
                "Motiu": ", ".join(freshness_reason_labels.get(reason, str(reason).replace("_", " ").capitalize())
                                   for reason in item.get("reasons", [])) or "—",
                "Detall proveïdor": item.get("detail") or "—",
            } for item in global_report.get("freshness", [])]
            if freshness_rows:
                st.markdown("#### Estat de les dades")
                freshness_counts = {}
                for item in freshness_rows:
                    freshness_counts[item["Estat"]] = freshness_counts.get(item["Estat"], 0) + 1
                status_cols = st.columns(min(4, max(1, len(freshness_counts))))
                for index, (label, count) in enumerate(sorted(freshness_counts.items())):
                    status_cols[index % len(status_cols)].metric(label, count)
                with st.expander("Detall per actiu", expanded=False):
                    for start in range(0, len(freshness_rows), 2):
                        cards = st.columns(2)
                        for offset, item in enumerate(freshness_rows[start:start + 2]):
                            with cards[offset].container(border=True):
                                st.markdown("**{} · {}**".format(item["Actiu"], item["Interval"]))
                                status = item["Estat"]
                                st.markdown("**{}**".format(status))
                                st.caption(
                                    "Última espelma: {} · Antiguitat: {} h · Historial: {} espelmes".format(
                                        item["Última espelma tancada UTC"],
                                        "—" if item["Antiguitat (h)"] is None else item["Antiguitat (h)"],
                                        "—" if item["Espelmes"] is None else item["Espelmes"],
                                    )
                                )
                                if item["Motiu"] != "—" or item["Detall proveïdor"] != "—":
                                    st.caption(item["Motiu"] if item["Motiu"] != "—" else item["Detall proveïdor"])
                st.caption("Només s'utilitzen espelmes tancades. Les sèries 4h endarrerides queden fora dels indicadors i de la confirmació RSI + MACD.")

            tactical = [row for row in eligible if row["interval"] == "4h"]
            daily = [row for row in eligible if row["interval"] == "1d"]
            aligned = global_report.get("cross_timeframe", [])
            structure_labels = {
                "confirmed_trend": "Tendència confirmada",
                "possible_reversal": "Possible gir (pendent del diari)",
                "incipient_recovery": "Recuperació incipient",
                "timeframe_divergence": "Divergència temporal",
                "weakness": "Feblesa",
                "mixed_structure": "Estructura mixta",
                "early_turn_watch": "Possible gir inicial (4h)",
                "insufficient_timeframes": "Intervals insuficients",
            }
            confirmation_labels = {
                "confirmed_both": "RSI + MACD confirmats en 1d i 4h",
                "daily_only": "Confirmació només diària",
                "4h_only": "Confirmació només 4h",
                "not_confirmed": "Sense confirmació RSI + MACD",
            }
            daily_by_symbol = {row["symbol"]: row for row in daily}
            tactical_by_symbol = {row["symbol"]: row for row in tactical}
            entry_data_quality = {item["symbol"]: item.get("data_quality_pct", 0) for item in global_report.get("risk_adjusted_relative_strength_coverage", [])}

            # Session-scoped transition detection: compare only consecutive fresh scans
            # visible to this dashboard session; no historical signal is fabricated.
            current_structures = {row["symbol"]: row.get("structure") for row in aligned}
            previous_structures = st.session_state.get("global_crypto_previous_structures")
            new_alerts = build_technical_alerts(global_report, previous_structures or {})
            alert_storage_ok = False
            inserted_alerts = []
            if paper_store:
                try:
                    inserted_alerts = paper_store.save_market_alerts(new_alerts)
                    stored_alerts = paper_store.load_market_alerts(days=90, limit=500)
                    persisted_keys = {item.get("dedupe_key") for item in stored_alerts}
                    expected_keys = {item.get("dedupe_key") for item in new_alerts}
                    missing_keys = expected_keys - persisted_keys
                    if missing_keys:
                        raise SupabaseStoreError(
                            "La lectura de verificació no troba {} alertes enviades.".format(len(missing_keys))
                        )
                    alert_storage_ok = True
                    st.success(
                        "Historial Supabase verificat: {} alertes noves inserides; {} ja existien o s'han deduplicat.".format(
                            len(inserted_alerts), max(0, len(new_alerts) - len(inserted_alerts))
                        )
                    )
                except SupabaseStoreError as alert_error:
                    stored_alerts = st.session_state.get("global_crypto_alert_history", [])
                    st.warning("No s'ha pogut verificar la persistència de l'historial d'alertes: " + str(alert_error))
            else:
                stored_alerts = st.session_state.get("global_crypto_alert_history", [])
                st.info("Sense Supabase: les alertes només es conserven durant aquesta sessió. Configura Supabase i la taula market_alert_events per mantenir l'historial després de reiniciar.")
            if not alert_storage_ok:
                current_keys = {item.get("dedupe_key") for item in new_alerts}
                stored_alerts = new_alerts + [item for item in stored_alerts if item.get("dedupe_key") not in current_keys]
                st.session_state["global_crypto_alert_history"] = stored_alerts[:500]
            if new_alerts:
                st.markdown("#### Alertes detectades")
                for start in range(0, len(new_alerts), 2):
                    cards = st.columns(2)
                    for offset, item in enumerate(new_alerts[start:start + 2]):
                        with cards[offset].container(border=True):
                            st.markdown("**{}**".format(item.get("asset", "—")))
                            st.markdown(item.get("label", "Alerta tècnica"))
                            st.caption(
                                ("Força relativa" if item.get("alert_class") == "relative_strength" else "Confirmació tècnica")
                                + " · No és una entrada de trading"
                            )
                            st.write(item.get("detail", "Sense detall addicional"))
            else:
                st.info("Cap alerta tècnica nova en aquesta lectura.")
            if stored_alerts:
                with st.expander("Historial d'alertes · últims 90 dies", expanded=False):
                    for item in stored_alerts[:30]:
                        with st.container(border=True):
                            st.markdown("**{} · {}**".format(
                                item.get("asset", "—"), item.get("label", "Alerta")
                            ))
                            st.caption("{} · {}".format(
                                "Força relativa" if item.get("event_type") == "relative_strength_outperformance" else "Confirmació tècnica",
                                str(item.get("created_at", item.get("daily_close", "Data no disponible")))[:16].replace("T", " ")
                            ))
                            st.write(item.get("detail", ""))
                    if len(stored_alerts) > 30:
                        st.caption("Es mostren les 30 alertes més recents de {} registres.".format(len(stored_alerts)))

            if previous_structures is not None:
                transitions = [{
                    "Actiu": symbol.replace("USDT", ""),
                    "Abans": structure_labels.get(previous_structures.get(symbol), previous_structures.get(symbol, "—")),
                    "Ara": structure_labels.get(category, category),
                } for symbol, category in current_structures.items()
                    if symbol in previous_structures and previous_structures[symbol] != category]
                if transitions:
                    st.markdown("#### Canvis de classificació")
                    for item in transitions:
                        with st.container(border=True):
                            st.markdown("**{}**".format(item["Actiu"]))
                            st.caption("{}  →  {}".format(item["Abans"], item["Ara"]))
                    confirmed = [item for item in transitions if item["Ara"] == "Tendència confirmada"]
                    if confirmed:
                        st.success("Confirmació tècnica multi-temporal: " + ", ".join(item["Actiu"] for item in confirmed))
            st.session_state["global_crypto_previous_structures"] = current_structures

            if aligned:
                st.markdown("#### Resum del mercat")
                st.caption("Vista mòbil: actiu, estat i rendiment. Les mètriques complementàries són a l'apartat desplegable.")
                summary_rows = []
                detail_rows = []
                for row in aligned:
                    d_row = daily_by_symbol.get(row["symbol"], {})
                    t_row = tactical_by_symbol.get(row["symbol"], {})
                    d_ind = d_row.get("indicators", {})
                    t_ind = t_row.get("indicators", {})
                    entry = classify_entry_opportunity(
                        d_row, t_row,
                        {"category": row.get("structure")},
                        relative_strength_20d_pp=row.get("relative_strength_vs_btc_20d_pp"),
                        data_quality_pct=entry_data_quality.get(row["symbol"], 100),
                    )
                    summary_rows.append({
                        "Actiu": row["symbol"].replace("USDT", ""),
                        "Estat": structure_labels.get(row.get("structure"), row.get("structure")),
                        "Context d'entrada": entry["label"],
                        "Qualitat /100": entry.get("quality_score"),
                        "Confirmació RSI + MACD": confirmation_labels.get(row.get("rsi_macd_confirmation"), "Sense dades"),
                        "7d %": row.get("return_7d_pct"),
                        "30d %": row.get("return_30d_pct"),
                    })
                    detail_rows.append({
                        "Actiu": row["symbol"].replace("USDT", ""),
                        "RSI diari": d_ind.get("rsi_14"),
                        "RSI 4h": t_ind.get("rsi_14"),
                        "MACD hist. diari": d_ind.get("macd_histogram"),
                        "MACD hist. 4h": t_ind.get("macd_histogram"),
                        "Confirmació RSI + MACD": confirmation_labels.get(row.get("rsi_macd_confirmation"), "Sense dades"),
                        "Força vs BTC 7d (pp)": row.get("relative_strength_vs_btc_7d_pct"),
                        "Força vs BTC 30d (pp)": row.get("relative_strength_vs_btc_30d_pct"),
                    })
                summary_rows.sort(
                    key=lambda item: (
                        item["30d %"] is not None,
                        item["30d %"] if item["30d %"] is not None else -999
                    ), reverse=True
                )

                # Visual market overview: preserve the underlying scoring and data.
                st.markdown("#### Mapa de rendiment · 7d / 30d")
                heatmap_rows = [
                    {"Actiu": item["Actiu"], "7 dies (%)": item["7d %"], "30 dies (%)": item["30d %"]}
                    for item in summary_rows
                    if item["7d %"] is not None or item["30d %"] is not None
                ]
                if heatmap_rows:
                    heatmap_frame = pd.DataFrame(heatmap_rows).set_index("Actiu")
                    for start in range(0, len(heatmap_rows), 2):
                        asset_cols = st.columns(2)
                        for offset, item in enumerate(heatmap_rows[start:start + 2]):
                            with asset_cols[offset].container(border=True):
                                st.markdown("**{}**".format(item["Actiu"]))
                                m1, m2 = st.columns(2)
                                m1.metric(
                                    "7 dies",
                                    "—" if item["7 dies (%)"] is None else "{:+.2f}%".format(item["7 dies (%)"]),
                                )
                                m2.metric(
                                    "30 dies",
                                    "—" if item["30 dies (%)"] is None else "{:+.2f}%".format(item["30 dies (%)"]),
                                )
                    heatmap_fig = px.imshow(heatmap_frame, text_auto=".2f", aspect="auto", color_continuous_scale=["#e3484d", "#091a2c", "#00b879"], color_continuous_midpoint=0, labels={"x": "Horitzó", "y": "Actiu", "color": "Canvi %"}, title="Rendiment per actiu · selecciona una cel·la per veure'n el detall")
                    heatmap_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=max(300, len(heatmap_rows)*48), margin=dict(l=8,r=8,t=55,b=8))
                    heatmap_event = st.plotly_chart(heatmap_fig, use_container_width=True, config={"displaylogo": False}, on_select="rerun", selection_mode="points")
                    selected_heatmap = (heatmap_event.selection.points or []) if heatmap_event else []
                    if selected_heatmap:
                        point = selected_heatmap[-1]
                        selected_asset = str(point.get("y", ""))
                        selected_horizon = str(point.get("x", ""))
                        selected_row = next((item for item in summary_rows if item["Actiu"] == selected_asset), None)
                        if selected_row:
                            st.markdown("**Detall seleccionat · {} · {}**".format(selected_asset, selected_horizon))
                            d1, d2, d3 = st.columns(3)
                            d1.metric("7 dies", "—" if selected_row["7d %"] is None else "{:+.2f}%".format(selected_row["7d %"]))
                            d2.metric("30 dies", "—" if selected_row["30d %"] is None else "{:+.2f}%".format(selected_row["30d %"]))
                            d3.metric("Força vs BTC 30d", "—" if selected_row["Força vs BTC 30d (pp)"] is None else "{:+.2f} pp".format(selected_row["Força vs BTC 30d (pp)"]))
                else:
                    st.info("No hi ha rendiments suficients per construir el mapa de mercat.")

                available_contexts = sorted({item["Context d'entrada"] for item in summary_rows})
                selected_context = st.selectbox(
                    "Filtra per classificació",
                    ["Tots"] + available_contexts,
                    key="global_crypto_context_filter",
                )
                visible_summary_rows = [
                    item for item in summary_rows
                    if selected_context == "Tots" or item["Context d'entrada"] == selected_context
                ]

                # Mobile-first summary: compact cards avoid wide tables on phone screens.
                for item in visible_summary_rows:
                    with st.container(border=True):
                        st.markdown("**{}** · {}".format(item["Actiu"], item["Estat"]))
                        st.caption("Entrada: {} · Confirmació: {}".format(
                            item["Context d'entrada"], item["Confirmació RSI + MACD"]
                        ))
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Qualitat", "—" if item["Qualitat /100"] is None else "{:.0f}/100".format(item["Qualitat /100"]))
                        c2.metric("7 dies", "—" if item["7d %"] is None else "{:+.2f}%".format(item["7d %"]))
                        c3.metric("30 dies", "—" if item["30d %"] is None else "{:+.2f}%".format(item["30d %"]))
                entry_details = []
                for row in aligned:
                    entry = classify_entry_opportunity(
                        daily_by_symbol.get(row["symbol"]),
                        tactical_by_symbol.get(row["symbol"]),
                        {"category": row.get("structure")},
                        relative_strength_20d_pp=row.get("relative_strength_vs_btc_20d_pp"),
                        data_quality_pct=entry_data_quality.get(row["symbol"], 100),
                    )
                    entry_details.append({
                        "Actiu": row["symbol"].replace("USDT", ""),
                        "Classificació": entry["label"],
                        "Qualitat /100": entry.get("quality_score"),
                        "Completesa dades %": entry.get("data_quality_pct"),
                        "Confirmació tècnica": entry.get("confirmation_status", "Sense dades"),
                        "Confirmació diària": "Sí" if entry.get("daily_confirmed") else "No",
                        "Confirmació 4h": "Sí" if entry.get("4h_confirmed") else "No",
                        "RSI diari": entry.get("daily_rsi"),
                        "RSI 4h": entry.get("4h_rsi"),
                        "Distància SMA20 diària %": entry.get("daily_extension_vs_sma20_pct"),
                        "Penalització risc": entry.get("risk_penalty"),
                        "Penalització deteriorament": entry.get("deterioration_penalty"),
                        "Confirmació 1d + 4h": "Sí" if entry.get("confirmed_both") else "No",
                        "Motius": " ".join(entry.get("reasons", [])),
                    })
                with st.expander("Classificació d'oportunitats i qualitat d'entrada", expanded=False):
                    render_mid_cards(pd.DataFrame(entry_details), width="stretch", hide_index=True)
                    st.caption("La qualitat /100 resta penalitzacions per volatilitat (>=80%/120%), drawdown (<=-30%/-40%) i deteriorament a 20 dies. Només es considera configuració confirmada si RSI i MACD són positius simultàniament en diari i 4h. No és una probabilitat d'èxit ni una ordre.")

                st.markdown("#### Evolució comparativa (base 100)")
                st.caption("Preus diaris tancats, normalitzats a 100 al començament del període disponible. Serveix per comparar rendiment relatiu, no el preu absolut.")
                history_symbols = sorted(
                    row["symbol"].replace("USDT", "")
                    for row in daily if row.get("normalized_history")
                )
                default_symbols = [symbol for symbol in ["BTC", "ETH", "PEPE", "HYPE"] if symbol in history_symbols]
                selected_symbols = st.multiselect(
                    "Actius del gràfic", history_symbols,
                    default=default_symbols, key="global_crypto_comparison_symbols"
                )
                chart_series = {}
                for row in daily:
                    symbol = row["symbol"].replace("USDT", "")
                    if symbol in selected_symbols and row.get("normalized_history"):
                        chart_series[symbol] = {
                            point["date"]: point["value"] for point in row["normalized_history"]
                        }
                if chart_series:
                    chart_frame = pd.DataFrame(chart_series).sort_index()
                    comparison_fig = px.line(chart_frame.reset_index(), x=chart_frame.index.name or "index", y=list(chart_frame.columns), title="Evolució normalitzada · activa/desactiva actius a la llegenda")
                    comparison_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=430, hovermode="x unified", xaxis_title="Data", yaxis_title="Índex (inici = 100)", margin=dict(l=8,r=8,t=55,b=8), xaxis_rangeslider_visible=True, legend_title="Actius")
                    st.plotly_chart(comparison_fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
                else:
                    st.info("No hi ha historial diari suficient per als actius seleccionats.")

                with st.expander("Indicadors visuals per actiu", expanded=False):
                    available_indicator_assets = [
                        row["symbol"].replace("USDT", "")
                        for row in aligned
                        if daily_by_symbol.get(row["symbol"], {}).get("indicators")
                        or tactical_by_symbol.get(row["symbol"], {}).get("indicators")
                    ]
                    if available_indicator_assets:
                        selected_indicator_asset = st.selectbox(
                            "Actiu per inspeccionar",
                            available_indicator_assets,
                            key="global_crypto_indicator_asset",
                        )
                        canonical_indicator_symbol = selected_indicator_asset + "USDT"
                        selected_daily = daily_by_symbol.get(canonical_indicator_symbol, {})
                        selected_tactical = tactical_by_symbol.get(canonical_indicator_symbol, {})
                        selected_daily_ind = selected_daily.get("indicators", {})
                        selected_tactical_ind = selected_tactical.get("indicators", {})
                        indicator_frame = pd.DataFrame([
                            {"Interval": "Diari", "RSI 14": selected_daily_ind.get("rsi_14"),
                             "Força vs BTC 30d (pp)": next((row.get("relative_strength_vs_btc_30d_pct") for row in aligned if row["symbol"] == canonical_indicator_symbol), None)},
                            {"Interval": "4 hores", "RSI 14": selected_tactical_ind.get("rsi_14"),
                             "Força vs BTC 30d (pp)": next((row.get("relative_strength_vs_btc_30d_pct") for row in aligned if row["symbol"] == canonical_indicator_symbol), None)},
                        ]).set_index("Interval")
                        st.markdown("**RSI i força relativa**")
                        indicator_fig = px.bar(indicator_frame.reset_index(), x="Interval", y=["RSI 14", "Força vs BTC 30d (pp)"], barmode="group", title="RSI i força relativa · passa el cursor per consultar valors")
                        indicator_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=320, margin=dict(l=8,r=8,t=55,b=8), legend_title="Indicador")
                        st.plotly_chart(indicator_fig, use_container_width=True, config={"displaylogo": False})
                        st.caption("RSI: escala 0–100. La força relativa indica punts percentuals respecte a BTC; no és rendibilitat absoluta.")
                    else:
                        st.info("No hi ha indicadors disponibles per als actius actuals.")

                with st.expander("Dades avançades · RSI, MACD, força relativa i risc", expanded=False):
                    rsi_rows = [{
                        "Actiu": item["Actiu"],
                        "RSI diari": item["RSI diari"],
                        "RSI 4h": item["RSI 4h"],
                    } for item in detail_rows]
                    macd_rows = [{
                        "Actiu": item["Actiu"],
                        "Histograma diari": item["MACD hist. diari"],
                        "Histograma 4h": item["MACD hist. 4h"],
                        "Confirmació RSI + MACD": item["Confirmació RSI + MACD"],
                    } for item in detail_rows]
                    relative_rows = [{
                        "Actiu": item["Actiu"],
                        "Vs BTC 7d (pp)": item["Força vs BTC 7d (pp)"],
                        "Vs BTC 30d (pp)": item["Força vs BTC 30d (pp)"],
                    } for item in detail_rows]
                    st.markdown("**RSI**")
                    render_mid_cards(pd.DataFrame(rsi_rows), width="stretch", hide_index=True)
                    st.markdown("**Histograma MACD i confirmació**")
                    render_mid_cards(pd.DataFrame(macd_rows), width="stretch", hide_index=True)
                    st.markdown("**Força relativa**")
                    render_mid_cards(pd.DataFrame(relative_rows), width="stretch", hide_index=True)
                    st.caption("Valor positiu: l'actiu ha superat BTC. Valor negatiu: ha quedat per sota. Els valors buits indiquen historial insuficient.")
                    st.markdown("**Risc i rendiment històric (diari)**")
                    risk_rows = []
                    for item in daily:
                        risk = item.get("risk_metrics", {})
                        risk_rows.append({
                            "Actiu": item["symbol"].replace("USDT", ""),
                            "Rend. 20d %": risk.get("return_20d_pct"),
                            "Rend. 60d %": risk.get("return_60d_pct"),
                            "Rend. 120d %": risk.get("return_120d_pct"),
                            "Vol. 20d anualitzada %": risk.get("realized_volatility_20d_pct_annualized"),
                            "Vol. 60d anualitzada %": risk.get("realized_volatility_60d_pct_annualized"),
                            "Drawdown màx. finestra %": risk.get("max_drawdown_120d_pct"),
                        })
                    render_mid_cards(pd.DataFrame(risk_rows), width="stretch", hide_index=True)
                    risk_relative_rows = [{
                        "Actiu": row["symbol"].replace("USDT", ""),
                        "Vs BTC 20d (pp)": row.get("relative_strength_vs_btc_20d_pp"),
                        "Vs BTC 60d (pp)": row.get("relative_strength_vs_btc_60d_pp"),
                        "Vs BTC 120d (pp)": row.get("relative_strength_vs_btc_120d_pp"),
                    } for row in aligned]
                    st.markdown("**Força relativa vs BTC — horitzons ampliats**")
                    render_mid_cards(pd.DataFrame(risk_relative_rows), width="stretch", hide_index=True)
                    st.caption("Volatilitat anualitzada aproximada a partir de rendiments diaris. Drawdown: caiguda màxima des d'un màxim anterior dins de les últimes 120 espelmes disponibles. Els horitzons sense historial suficient queden buits.")
                    st.markdown("**Rànquing de força relativa ajustada pel risc**")
                    adjusted_rows = [{
                        "Actiu": item["symbol"].replace("USDT", ""),
                        "Puntuació composta / 100": item["score"],
                        "Momentum / 100": item["momentum_percentile"],
                        "Qualitat del risc / 100": item["risk_quality_percentile"],
                        "Aportació momentum (70%)": round(item["momentum_percentile"] * 0.70, 2),
                        "Aportació risc (30%)": round(item["risk_quality_percentile"] * 0.30, 2),
                        "Vs BTC 20d (pp)": item["relative_strength_20d_pp"],
                        "Vs BTC 60d (pp)": item["relative_strength_60d_pp"],
                        "Vs BTC 120d (pp)": item["relative_strength_120d_pp"],
                        "Vol. 20d anualitzada %": item["volatility_20d_pct_annualized"],
                        "Drawdown màx. %": item["max_drawdown_120d_pct"],
                    } for item in global_report.get("risk_adjusted_relative_strength", [])]
                    if adjusted_rows:
                        render_mid_cards(pd.DataFrame(adjusted_rows).round(2), width="stretch", hide_index=True)
                    else:
                        st.info("Cap actiu té ara mateix tots els horitzons i mètriques necessaris per entrar al rànquing complet.")
                    coverage_rows = [{
                        "Actiu": item["symbol"].replace("USDT", ""),
                        "Completesa de dades %": item["data_quality_pct"],
                        "Components disponibles": str(item["available_components"]) + "/" + str(item["total_components"]),
                        "Estat": "Completes" if item["ranking_status"] == "complete" else "Historial insuficient",
                        "Mètriques absents": ", ".join({
                            "rs20": "força relativa 20d",
                            "rs60": "força relativa 60d",
                            "rs120": "força relativa 120d",
                            "vol20": "volatilitat 20d",
                            "drawdown": "drawdown 120d",
                        }.get(key, key) for key in item["missing_components"]) or "—",
                        "Última vela diària UTC": item.get("latest_daily_candle_close") or "—",
                        "Antiguitat dades (h)": item.get("daily_data_age_hours"),
                        "Components que falten": ", ".join(item["missing_components"]) or "—",
                    } for item in global_report.get("risk_adjusted_relative_strength_coverage", [])]
                    if coverage_rows:
                        st.markdown("**Completesa i actualització de dades del rànquing**")
                        render_mid_cards(pd.DataFrame(coverage_rows), width="stretch", hide_index=True)
                    st.caption("Les dues subpuntuacions són independents: Momentum mesura força relativa vs BTC (40% 20d, 35% 60d, 25% 120d); Qualitat del risc mesura menor volatilitat (60%) i drawdown menys profund (40%). La puntuació composta combina aquestes dues dimensions (70% momentum, 30% risc); no les confonguis. Només competeixen actius amb els cinc components disponibles. La completesa indica si hi ha totes les mètriques; l’antiguitat indica quan s’ha tancat l’última vela diària. No és una probabilitat ni un senyal de compra.")
                st.caption("Els rendiments són variacions històriques, no previsions ni recomanacions d'operar.")

            with st.expander("Consulta tècnica avançada · dades completes", expanded=False):
                if tactical:
                    st.markdown("#### Rànquing tàctic - 4 hores")
                    tactical_rows = []
                    for row in tactical:
                        ind = row["indicators"]
                        tactical_rows.append({
                            "Actiu": row["symbol"],
                            "Preu": row["latest_close"],
                            "RSI 14": ind["rsi_14"],
                            "MACD": ind["macd_12_26"],
                            "Histograma MACD": ind["macd_histogram"],
                            "Canvi histograma": ind["macd_histogram_change"],
                            "Senyal MACD": ind["macd_signal_9"],
                            "SMA 20": ind["sma_20"],
                            "SMA 50": ind["sma_50"],
                            "Volatilitat %": ind["realized_volatility_pct_annualized_approx"],
                            "Puntuació": row["technical_screen_score"],
                            "Antiguitat (min)": round(row["age_seconds"] / 60, 1),
                        })
                    tactical_rows.sort(key=lambda item: item["Puntuació"], reverse=True)
                    render_mid_cards(pd.DataFrame(tactical_rows), width="stretch", hide_index=True)

                if daily:
                    st.markdown("#### Confirmació de tendència - diari")
                    daily_rows = []
                    for row in daily:
                        ind = row["indicators"]
                        daily_rows.append({
                            "Actiu": row["symbol"],
                            "Preu": row["latest_close"],
                            "RSI 14": ind["rsi_14"],
                            "MACD": ind["macd_12_26"],
                            "Senyal MACD": ind["macd_signal_9"],
                            "Histograma MACD": ind["macd_histogram"],
                            "Canvi histograma": ind["macd_histogram_change"],
                            "SMA 20": ind["sma_20"],
                            "SMA 50": ind["sma_50"],
                            "Puntuació": row["technical_screen_score"],
                            "Antiguitat (h)": round(row["age_seconds"] / 3600, 1),
                        })
                    daily_rows.sort(key=lambda item: item["Puntuació"], reverse=True)
                    render_mid_cards(pd.DataFrame(daily_rows), width="stretch", hide_index=True)

                if aligned:
                    st.markdown("#### Alineació multi-temporal")
                    alignment_rows = [{
                        "Actiu": row["symbol"],
                        "Puntuació diària": row["daily_score"],
                        "Puntuació 4h": row["4h_score"],
                        "Alineació": row["alignment_score"],
                        "Classificació": structure_labels.get(row.get("structure"), row.get("structure")),
                        "Confirmació RSI + MACD": confirmation_labels.get(row.get("rsi_macd_confirmation"), "Sense dades"),
                        "Lectura": row.get("structure_explanation", ""),
                    } for row in aligned]
                    render_mid_cards(pd.DataFrame(alignment_rows), width="stretch", hide_index=True)
                st.caption("Les puntuacions tècniques són filtres descriptius, no probabilitats, rendiments esperats ni senyals d'operació.")

            if rejected:
                reason_labels = {
                    "stale_data": "Dades antigues",
                    "insufficient_history": "Historial insuficient",
                    "invalid_ohlc": "Preus inconsistents",
                    "future_timestamp": "Data futura",
                    "mixed_symbol": "Símbol inconsistent",
                    "mixed_interval": "Intervals barrejats",
                }
                rejected_rows = [{
                    "Actiu": row.get("symbol"),
                    "Interval": row.get("interval"),
                    "Espelmes": row.get("bars"),
                    "Motiu": ", ".join(reason_labels.get(reason, reason.replace("_", " ")) for reason in row.get("reasons", [])),
                } for row in rejected]
                with st.expander("Sèries descartades per qualitat de dades", expanded=False):
                    render_mid_cards(pd.DataFrame(rejected_rows), width="stretch", hide_index=True)

            if unavailable_items:
                reason_labels = {
                    "pair_not_listed_on_binance_spot": "El parell no consta al catàleg actual de Binance Spot",
                    "pair_not_trading_on_binance_spot": "El parell consta al catàleg, però no està en estat TRADING",
                    "spot_trading_not_allowed_for_pair": "El parell no permet operativa Spot",
                    "no_binance_pair_mapping": "No hi ha una equivalència configurada amb Binance",
                    "spot_listing_check_failed": "No s'ha pogut verificar el catàleg Spot",
                    "rate_limit": "Límit de consultes de Binance assolit",
                    "provider_request_failed": "Ha fallat la consulta al proveïdor",
                    "invalid_provider_response": "Resposta del proveïdor invàlida",
                    "provider_error": "Error del proveïdor de dades",
                }
                if preflight_items:
                    grouped_preflight = {}
                    for item in preflight_items:
                        key = (item.get("symbol", "—"), item.get("provider_symbol", "—"), item.get("reason", "unknown"))
                        grouped_preflight.setdefault(key, set()).add(item.get("interval", "—"))
                    preflight_rows = [{
                        "Actiu": symbol,
                        "Parell Binance": pair or "—",
                        "Intervals omesos": ", ".join(sorted(intervals)),
                        "Motiu": reason_labels.get(reason, reason.replace("_", " ").capitalize()),
                    } for (symbol, pair, reason), intervals in sorted(grouped_preflight.items())]
                    with st.expander("Diagnòstic avançat · actius omesos al catàleg Binance Spot", expanded=False):
                        render_mid_cards(pd.DataFrame(preflight_rows), width="stretch", hide_index=True)
                        st.caption("Aquests parells s'han descartat abans de demanar espelmes. Cada fila agrupa els intervals afectats per actiu.")

                if request_failures:
                    failure_rows = [{
                        "Actiu": item.get("symbol", "—"),
                        "Parell Binance": item.get("provider_symbol", "—"),
                        "Interval": item.get("interval", "—"),
                        "Motiu": reason_labels.get(item.get("reason"), str(item.get("reason", "unknown")).replace("_", " ").capitalize()),
                        "Detall": item.get("detail", ""),
                    } for item in request_failures]
                    with st.expander("Diagnòstic avançat · errors de dades", expanded=False):
                        render_mid_cards(pd.DataFrame(failure_rows), width="stretch", hide_index=True)

                availability_counts = global_report.get("availability_counts", {})
                if availability_counts:
                    with st.expander("Resum de causes per interval", expanded=False):
                        render_mid_cards(pd.DataFrame([
                            {"Causa": reason_labels.get(reason, reason.replace("_", " ").capitalize()),
                             "Intervals afectats": count}
                            for reason, count in sorted(availability_counts.items())
                        ]), width="stretch", hide_index=True)

            st.caption("La puntuació tècnica és un filtre descriptiu basat en tendència, MACD, mitjanes mòbils i RSI. No representa una probabilitat, rendiment esperat ni recomanació d'inversió. Encara no s'hi inclouen dades fonamentals ni catalitzadors.")
        except Exception as error:
            st.error("Global crypto scan failed: " + str(error))
    else:
        st.info("Select the scan button to fetch the 13-asset crypto watchlist and calculate fresh indicators. No market request is made until you start the scan.")

    st.divider()
    st.subheader("Equities, ETFs and commodities - daily history")
    fd_key = secret("FINANCIALDATA_API_KEY")
    if not fd_key:
        st.info("Optional: add FINANCIALDATA_API_KEY in hosting Secrets to activate daily history for the equity, ETF and commodity seed lists.")
    else:
        st.caption("FinancialData.Net daily OHLCV · read-only · up to 120 observations per instrument · weekend-aware freshness window of 5 days.")
        if st.button("Fetch global daily asset data", key="run_global_daily_asset_scan"):
            get_global_daily_asset_analysis.clear()
            st.session_state["global_daily_asset_scan_requested"] = True
        if st.session_state.get("global_daily_asset_scan_requested"):
            try:
                with st.spinner("Requesting daily history for equities, ETFs and commodities..."):
                    daily_report = get_global_daily_asset_analysis(fd_key)
                good = [row for row in daily_report["analyses"] if row["eligible"]]
                bad = [row for row in daily_report["analyses"] if not row["eligible"]]
                m1, m2, m3 = st.columns(3)
                m1.metric("Valid instruments", len(good))
                m2.metric("Rejected histories", len(bad))
                m3.metric("Unavailable requests", len(daily_report["unavailable"]))
                if good:
                    rows = []
                    for item in good:
                        ind = item["indicators"]
                        rows.append({
                            "Asset class": item["asset_class"], "Symbol": item["symbol"],
                            "Last close": item["latest_close"], "RSI 14": ind["rsi_14"],
                            "MACD": ind["macd_12_26"], "SMA 20": ind["sma_20"],
                            "SMA 50": ind["sma_50"],
                            "Technical score": item["technical_screen_score"],
                            "Data age (days)": round(item["age_seconds"] / 86400, 2),
                        })
                    rows.sort(key=lambda item: item["Technical score"], reverse=True)
                    render_mid_cards(pd.DataFrame(rows), width="stretch", hide_index=True)
                if bad:
                    st.markdown("#### Rejected histories")
                    render_mid_cards(pd.DataFrame([{
                        "Asset class": item.get("asset_class"), "Symbol": item.get("symbol"),
                        "Reasons": ", ".join(item.get("reasons", [])),
                    } for item in bad]), width="stretch", hide_index=True)
                if daily_report["quality"]:
                    st.markdown("#### Rejected source records (excluded from indicators)")
                    render_mid_cards(pd.DataFrame(daily_report["quality"]),
                        width="stretch", hide_index=True)
                if daily_report["unavailable"]:
                    st.markdown("#### Provider unavailable / no exact symbol data")
                    render_mid_cards(pd.DataFrame(daily_report["unavailable"]),
                        width="stretch", hide_index=True)
                st.caption("FinancialData.Net historical daily data. This feed does not imply real-time prices or verified subscription entitlement for every symbol. Technical screening only; no paper positions are changed.")
            except Exception as error:
                st.error("Global daily asset scan failed: " + str(error))

    st.divider()
    st.subheader("Forex - daily history")
    av_key = secret("ALPHA_VANTAGE_API_KEY")
    if not av_key:
        st.info("Optional: add ALPHA_VANTAGE_API_KEY in hosting Secrets to activate four daily FX pairs. A full scan uses four API requests.")
    else:
        st.caption("Alpha Vantage FX_DAILY · historical daily candles · cached for 15 minutes · five-calendar-day freshness window. FX volume is not supplied and is excluded.")
        if st.button("Fetch daily FX data", key="run_global_fx_scan"):
            get_global_fx_analysis.clear()
            st.session_state["global_fx_scan_requested"] = True
        if st.session_state.get("global_fx_scan_requested"):
            try:
                with st.spinner("Requesting daily FX history..."):
                    fx_report = get_global_fx_analysis(av_key)
                valid = [item for item in fx_report["analyses"] if item["eligible"]]
                rejected = [item for item in fx_report["analyses"] if not item["eligible"]]
                f1, f2, f3 = st.columns(3)
                f1.metric("Valid FX pairs", len(valid))
                f2.metric("Rejected histories", len(rejected))
                f3.metric("Unavailable requests", len(fx_report["unavailable"]))
                if valid:
                    fx_rows = []
                    for item in valid:
                        ind = item["indicators"]
                        fx_rows.append({
                            "Pair": item["symbol"], "Last close": item["latest_close"],
                            "RSI 14": ind["rsi_14"], "MACD": ind["macd_12_26"],
                            "SMA 20": ind["sma_20"], "SMA 50": ind["sma_50"],
                            "Technical score": item["technical_screen_score"],
                            "Data age (days)": round(item["age_seconds"] / 86400, 2),
                            "Volume": "Not provided",
                        })
                    fx_rows.sort(key=lambda item: item["Technical score"], reverse=True)
                    render_mid_cards(pd.DataFrame(fx_rows), width="stretch", hide_index=True)
                if rejected:
                    st.markdown("#### Rejected FX histories")
                    render_mid_cards(pd.DataFrame([{
                        "Pair": item.get("symbol"), "Reasons": ", ".join(item.get("reasons", [])),
                    } for item in rejected]), width="stretch", hide_index=True)
                if fx_report["unavailable"]:
                    st.markdown("#### FX provider unavailable")
                    render_mid_cards(pd.DataFrame(fx_report["unavailable"]), width="stretch", hide_index=True)
                st.caption("The FX technical score uses price candles only. Alpha Vantage does not supply centralized FX volume here; no volume/liquidity score is inferred. Historical data is not a real-time quote and does not modify paper positions.")
            except Exception as error:
                st.error("Global FX scan failed: " + str(error))


with scanner_tab:
    st.subheader("Market Scanner v1 - independent paper portfolio")
    st.caption("Read-only view of the standalone Binance Spot scanner. Its paper portfolio is separate from the manual AI Trading Desk portfolio.")
    if not supabase_url or not supabase_service_key:
        st.info("Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to view scanner data.")
    else:
        try:
            scanner_store = ScannerStore(supabase_url, supabase_service_key)
            scanner_state = scanner_store.load_state()
            scanner_candidates = scanner_store.latest_candidates(limit=50)
            if scanner_state:
                scanner_summary = portfolio_summary(scanner_state)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Scanner equity", "USD {:.2f}".format(scanner_summary["equity_usd"]))
                c2.metric("Available cash", "USD {:.2f}".format(scanner_summary["cash_usd"]))
                c3.metric("Open positions", scanner_summary["open_positions"])
                c4.metric("Closed trades", scanner_summary["closed_trades"])
                st.caption("Scanner realized P&L: USD {:.2f} | Unrealized P&L: USD {:.2f}".format(
                    scanner_summary["realized_pnl_usd"], scanner_summary["unrealized_pnl_usd"]))
                if scanner_state.get("open_positions"):
                    st.markdown("#### Scanner open paper positions")
                    render_mid_cards(pd.DataFrame(scanner_state["open_positions"]), width="stretch", hide_index=True)
                if scanner_state.get("closed_trades"):
                    st.markdown("#### Operacions paper tancades (històric)")
                    st.caption("Registre d'operacions anteriors. No implica que aquests actius continuïn cotitzant a Binance Spot ni que siguin candidats actuals.")
                    render_mid_cards(pd.DataFrame(scanner_state["closed_trades"][-50:]), width="stretch", hide_index=True)
            else:
                st.info("The scanner has not completed its first cycle yet.")
            st.markdown("#### Candidats de l'últim escaneig")
            st.caption("Aquesta llista prové de l'últim cicle complet i només inclou parells que Binance Spot marcava com a actius en aquell escaneig. No barreja operacions històriques tancades amb candidats actuals.")
            if scanner_candidates:
                ready_count = sum(bool(row.get("auto_entry_eligible")) for row in scanner_candidates)
                watch_count = sum(row.get("entry_status") == "WATCH" for row in scanner_candidates)
                near_miss_count = sum(row.get("entry_status") == "NEAR_MISS" for row in scanner_candidates)
                rejected_count = sum(row.get("entry_status") == "FILTERED" for row in scanner_candidates)
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Preparats per entrar", ready_count)
                d2.metric("En vigilància", watch_count)
                d3.metric("A prop del mínim", near_miss_count)
                d4.metric("Descartats", rejected_count)
                st.caption("No s'han modificat els llindars d'entrada. 'Preparat' exigeix puntuació mínima i tots els filtres obligatoris; la resta es classifica per facilitar el diagnòstic.")
                display_rows = []
                for row in scanner_candidates:
                    status_labels = {
                        "READY": "PREPARAT",
                        "WATCH": "VIGILÀNCIA",
                        "NEAR_MISS": "A PROP",
                        "FILTERED": "DESCARTAT",
                        "LEGACY_UNAVAILABLE": "DADES INCOMPLETES",
                    }
                    display_rows.append({
                        "Estat": status_labels.get(row.get("entry_status"), "ANTIC"),
                        "Parell": row.get("symbol"),
                        "Puntuació": row.get("score"),
                        "Falten punts": row.get("score_gap_to_auto_entry"),
                        "Filtres obligatoris pendents": ", ".join(row.get("hard_gate_failures", [])) or "Cap",
                        "Alertes tècniques": ", ".join(row.get("quality_warnings", [])) or "Cap",
                        "Entrada automàtica": "Sí" if row.get("auto_entry_eligible") else "No",
                    })
                render_mid_cards(pd.DataFrame(display_rows), width="stretch", hide_index=True)
                with st.expander("Dades tècniques completes de cada candidat"):
                    render_mid_cards(pd.DataFrame(scanner_candidates), width="stretch", hide_index=True)
            else:
                st.info("No scanner candidates stored yet.")
        except (ScannerStoreError, ValueError) as error:
            st.error("Could not load Market Scanner data: " + str(error))


with cross_market_tab:
    st.subheader("Cross-market risk monitor")
    st.caption("BTC versus S&P 500 (SPY) and Nasdaq 100 (QQQ) · synchronized 15-minute candles · read-only.")
    st.warning("Research only. This monitor does not create signals for entry, modify the Market Scanner, or change either paper portfolio.")
    st.write("The detector compares the latest closed 15-minute and 1-hour returns, checks whether the three series are synchronized, and calculates rolling 15-minute return correlations.")
    if st.button("Fetch BTC, S&P 500 and Nasdaq data", key="run_cross_market_scan"):
        get_cross_market_report.clear()
        st.session_state["cross_market_scan_requested"] = True
    if not st.session_state.get("cross_market_scan_requested"):
        st.info("Start the scan to request fresh public market data. No intraday market request is made until you press the button.")
    else:
        try:
            with st.spinner("Fetching synchronized 15-minute candles from Binance and Twelve Data..."):
                cross_report = get_cross_market_report(twelve_key)
            if cross_report.get("provider_unavailable"):
                st.markdown("#### Provider availability")
                render_mid_cards(pd.DataFrame(cross_report["provider_unavailable"]), width="stretch", hide_index=True)
            if cross_report.get("status") == "ok":
                st.markdown("#### Current market regime")
                st.metric("Cross-market reading", cross_report["label"])
                st.caption(cross_report["reason"])
                c1, c2, c3 = st.columns(3)
                c1.metric("Latest closed candle age", "{} min".format(cross_report["age_minutes"]))
                c2.metric("Timestamp difference", "{} min".format(cross_report["sync_difference_minutes"]))
                c3.metric("Common 15m candles", cross_report["common_bars"])
                asset_labels = {"BTCUSDT": "BTC / USD", "SPY": "S&P 500 (SPY)", "QQQ": "Nasdaq 100 (QQQ)"}
                asset_rows = [{
                    "Market": asset_labels[symbol],
                    "Latest close": values["price"],
                    "Return 15m %": values["return_15m_pct"],
                    "Return 1h %": values["return_1h_pct"],
                    "Latest closed candle UTC": values["latest_candle_utc"],
                } for symbol, values in cross_report["assets"].items()]
                render_mid_cards(pd.DataFrame(asset_rows).round(4), width="stretch", hide_index=True)
                correlation_rows = [{
                    "Pair": label.replace("_15m", "").replace("_", " / "),
                    "Correlation (15m returns)": value,
                } for label, value in cross_report["correlations"].items()]
                st.markdown("#### Rolling correlations")
                render_mid_cards(pd.DataFrame(correlation_rows).round(3), width="stretch", hide_index=True)
                st.caption("Correlations are descriptive, not causal. They are calculated over up to the latest 24 synchronized 15-minute returns. Correlation can change quickly and is not a standalone trading signal.")
            else:
                st.warning(cross_report.get("label", "Cross-market data unavailable"))
                st.write(cross_report.get("reason", "No valid synchronized market data was returned."))
                if cross_report.get("age_minutes") is not None:
                    st.caption("Latest candle age: {} minutes · timestamp difference: {} minutes".format(
                        cross_report["age_minutes"], cross_report.get("sync_difference_minutes", "—")))
        except Exception as error:
            st.error("Cross-market scan failed: " + str(error))


with bitunix_tab:
    st.subheader("Bitunix account connection")
    st.caption("Private account data · signed REST requests · read-only endpoints only.")
    st.warning("Read-only integration. This screen contains no order placement, transfer, withdrawal, or account-mutation functionality.")
    bitunix_api_key = secret("BITUNIX_API_KEY")
    bitunix_api_secret = secret("BITUNIX_API_SECRET")
    if not bitunix_api_key or not bitunix_api_secret:
        st.info("Add BITUNIX_API_KEY and BITUNIX_API_SECRET to Streamlit Community Cloud → App settings → Secrets.")
    else:
        st.success("Bitunix credentials detected in hosting Secrets. Credential values are never displayed.")
        if st.button("Read Bitunix account", key="read_bitunix_account"):
            from bitunix.client import BitunixAPIError, BitunixReadOnlyClient
            client = BitunixReadOnlyClient(bitunix_api_key, bitunix_api_secret)
            snapshot = {"spot_error": None, "futures_account_error": None, "positions_error": None}
            try:
                snapshot["spot_balances"] = client.get_spot_balances()
            except BitunixAPIError as error:
                snapshot["spot_error"] = str(error)
            try:
                snapshot["futures_account"] = client.get_futures_account("USDT")
            except BitunixAPIError as error:
                snapshot["futures_account_error"] = str(error)
            try:
                snapshot["futures_positions"] = client.get_futures_positions()
            except BitunixAPIError as error:
                snapshot["positions_error"] = str(error)
            st.session_state["bitunix_readonly_snapshot"] = snapshot

        snapshot = st.session_state.get("bitunix_readonly_snapshot")
        if snapshot:
            from bitunix.portfolio import build_portfolio_overview

            overview = build_portfolio_overview(snapshot)
            st.markdown("#### Real portfolio overview")
            metric_cols = st.columns(3)
            metric_cols[0].metric("Spot assets", overview["spot_asset_count"])
            metric_cols[1].metric("Open Futures positions", overview["open_futures_positions"])
            metric_cols[2].metric("Futures accounts", len(overview["futures_accounts"]))
            st.markdown("#### Spot assets")
            if snapshot.get("spot_error"):
                st.error("Spot: " + snapshot["spot_error"])
            elif overview["spot_assets"]:
                from decimal import Decimal, InvalidOperation

                def format_spot_amount(value):
                    try:
                        amount = Decimal(str(value))
                    except (InvalidOperation, TypeError, ValueError):
                        return "—"
                    if not amount.is_finite():
                        return "—"
                    rendered = format(amount, ".10f").rstrip("0").rstrip(".")
                    return rendered or "0"

                for asset in overview["spot_assets"]:
                    with st.container(border=True):
                        st.markdown("**{}**".format(asset["asset"]))
                        st.caption(
                            "Disponible: {}  ·  Bloquejat: {}  ·  Total: {}".format(
                                format_spot_amount(asset["available"]),
                                format_spot_amount(asset["locked"]),
                                format_spot_amount(asset["total"]),
                            )
                        )
            else:
                st.info("Bitunix returned no Spot balances.")
            st.caption(
                "Real Bitunix account data only. Fiat valuation is not calculated here; "
                "paper-trading balances and positions remain separate and unchanged."
            )
            st.markdown("#### Futures account (USDT)")
            if snapshot.get("futures_account_error"):
                st.error("Futures account: " + snapshot["futures_account_error"])
            else:
                futures_rows = snapshot.get("futures_account", [])
                if futures_rows:
                    render_mid_cards(pd.DataFrame(futures_rows), width="stretch", hide_index=True)
                else:
                    st.info("Bitunix returned no USDT Futures account data.")
            st.markdown("#### Open Futures positions")
            if snapshot.get("positions_error"):
                st.error("Positions: " + snapshot["positions_error"])
            else:
                position_rows = snapshot.get("futures_positions", [])
                if position_rows:
                    render_mid_cards(pd.DataFrame(position_rows), width="stretch", hide_index=True)
                else:
                    st.info("No open Futures positions returned.")
            st.caption("Read-only snapshot. Data is requested only when you press the button; no trading action is available.")