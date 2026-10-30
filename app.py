import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone

from trading_desk import (
    Signal, evaluate_signal, new_portfolio, paper_entry, paper_exit,
    portfolio_summary, mark_position, STARTING_CAPITAL_USD,
)

st.set_page_config(page_title="Crypto & Equities", layout="wide")
st.title("Crypto & Equities Dashboard")

def secret(k):
    try:
        return str(st.secrets.get(k, "")).strip()
    except Exception:
        return ""

pw = secret("DASHBOARD_PASSWORD")
if not pw:
    st.error("Set DASHBOARD_PASSWORD, CMC_API_KEY and TWELVE_DATA_API_KEY in hosting Secrets.")
    st.stop()
if st.text_input("Password", type="password") != pw:
    st.stop()

cmc, td = secret("CMC_API_KEY"), secret("TWELVE_DATA_API_KEY")
if not cmc or not td:
    st.error("Missing API keys in hosting Secrets.")
    st.stop()

@st.cache_data(ttl=60)
def get_crypto(key):
    r = requests.get(
        "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
        headers={"X-CMC_PRO_API_KEY": key},
        params={"symbol": "BTC,ETH,SOL,LINK,XLM,SUI,HYPE", "convert": "USD"},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("status", {}).get("error_code", 0):
        raise RuntimeError(d["status"].get("error_message", "CMC error"))
    rows = []
    for symbol in ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"]:
        value = d.get("data", {}).get(symbol, [])
        if isinstance(value, dict):
            value = [value]
        quote = value[0].get("quote", {}).get("USD", {}) if value else {}
        rows.append({
            "Asset": symbol,
            "Price USD": quote.get("price"),
            "24h %": quote.get("percent_change_24h"),
            "24h Volume USD": quote.get("volume_24h"),
            "Updated": quote.get("last_updated"),
            "Source": "CoinMarketCap",
        })
    return rows

@st.cache_data(ttl=60)
def get_quote(symbol, key):
    r = requests.get(
        "https://api.twelvedata.com/quote",
        params={"symbol": symbol, "apikey": key},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("status") == "error" or "code" in d:
        raise RuntimeError(d.get("message", "Twelve Data error"))
    price = d.get("close") or d.get("price")
    return {
        "Asset": symbol,
        "Price USD": float(price) if price else None,
        "24h %": float(d["percent_change"]) if d.get("percent_change") else None,
        "Updated": d.get("datetime"),
        "Source": "Twelve Data",
    }

if st.button("Refresh market data"):
    get_crypto.clear()
    get_quote.clear()

tab_market, tab_desk = st.tabs(["Market dashboard", "AI Crypto Trading Desk"])

with tab_market:
    st.caption("Checked at " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    st.subheader("Crypto Â· CoinMarketCap")
    try:
        crypto_rows = get_crypto(cmc)
        st.dataframe(pd.DataFrame(crypto_rows), use_container_width=True, hide_index=True)
    except Exception as exc:
        crypto_rows = []
        st.error("CMC request failed: " + str(exc))
    st.subheader("Stocks and ETFs Â· Twelve Data")
    symbols = st.multiselect(
        "Symbols",
        ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "SPY", "QQQ"],
        ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
    )
    rows = []
    for symbol in symbols:
        try:
            rows.append(get_quote(symbol, td))
        except Exception as exc:
            st.warning(symbol + ": " + str(exc))
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Informational market snapshots only. No trade execution.")

with tab_desk:
    st.subheader("Paper Trading Â· virtual capital")
    st.warning("Simulation only. No exchange orders, wallet connections, or real funds are used.")
    if "paper_portfolio" not in st.session_state:
        st.session_state.paper_portfolio = new_portfolio(STARTING_CAPITAL_USD)
    if "desk_last_result" not in st.session_state:
        st.session_state.desk_last_result = None

    portfolio = st.session_state.paper_portfolio
    summary = portfolio_summary(portfolio)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Virtual equity", f"${summary['equity_usd']:.2f}")
    c2.metric("Cash available", f"${summary['cash_usd']:.2f}")
    c3.metric("Realized P&L", f"${summary['realized_pnl_usd']:.2f}")
    c4.metric("Unrealized P&L", f"${summary['unrealized_pnl_usd']:.2f}")
    st.caption(
        f"Starting capital: ${portfolio['starting_capital']:.2f} Â· "
        f"Return: {summary['total_return_pct']:.2f}% Â· "
        f"Open positions: {summary['open_positions']} Â· Closed trades: {summary['closed_trades']}"
    )

    st.markdown("#### 5-agent pipeline")
    st.write(
        "Scout: signal intake â Filter: hard rules â Analyst: risk review â "
        "Sniper: simulated entry â Guard: stop-loss and exposure controls."
    )
    st.caption(
        "In this first increment, candidates and on-chain Solana metrics are entered manually. "
        "The 640-wallet scanner and automated holder/bundle analytics are not connected yet."
    )

    with st.form("signal_form"):
        market = st.selectbox("Market", ["major", "solana"], format_func=lambda x: "BTC / ETH / major altcoins" if x == "major" else "Solana tokens / memecoins")
        if market == "major":
            asset = st.selectbox("Asset", ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"])
        else:
            asset = st.text_input("Token symbol or identifier", placeholder="e.g. TOKEN")
        price = st.number_input("Reference price (USD)", min_value=0.00000001, value=1.0, format="%.8f")
        stop_pct = st.slider("Stop Loss (%)", min_value=1, max_value=30, value=10)
        if market == "major":
            volume = st.number_input("24h volume (USD)", min_value=0.0, value=10000000.0, step=100000.0)
            gain45 = st.number_input("45-minute gain (%) if known; use 0 if unavailable", min_value=-100.0, max_value=1000.0, value=0.0)
            submitted = st.form_submit_button("Run agents and simulate entry")
            if submitted:
                signal = Signal(asset=asset, market=market, price_usd=price, volume_24h_usd=volume, gain_45m_pct=gain45, source="manual/CMC cross-check")
        else:
            liquidity = st.number_input("Liquidity (USD)", min_value=0.0, value=50000.0, step=1000.0)
            top10 = st.number_input("Top-10 holder concentration (%)", min_value=0.0, max_value=100.0, value=25.0)
            dev = st.number_input("Developer wallet share (%)", min_value=0.0, max_value=100.0, value=2.0)
            bundled = st.selectbox("Bundled buys in first 60 seconds?", [False, True])
            gain45 = st.number_input("Price gain in last 45 minutes (%)", min_value=-100.0, max_value=1000.0, value=12.0)
            source_sold = st.selectbox("Source wallet already sold?", [False, True])
            submitted = st.form_submit_button("Run agents and simulate entry")
            if submitted:
                signal = Signal(
                    asset=asset, market=market, price_usd=price, liquidity_usd=liquidity,
                    top10_holder_pct=top10, dev_wallet_pct=dev,
                    bundled_buys_first_60s=bundled, gain_45m_pct=gain45,
                    source_wallet_sold=source_sold, source="manual/on-chain metrics",
                )

    if submitted:
        result = evaluate_signal(signal)
        st.session_state.desk_last_result = {"signal": signal, "result": result}
        if result["approved"]:
            try:
                position = paper_entry(portfolio, signal, stop_loss_pct=float(stop_pct))
                st.success(f"Signal approved. Paper position opened: ${position['notional_usd']:.2f} notional; stop ${position['stop_price']:.8f}.")
            except ValueError as exc:
                st.error(str(exc))
        else:
            st.error("Signal rejected. No paper position opened.")
    last = st.session_state.desk_last_result
    if last:
        st.markdown("#### Latest filter result")
        st.write(f"**{last['signal'].asset}** Â· {last['signal'].market} Â· {'APPROVED' if last['result']['approved'] else 'REJECTED'}")
        if last["result"]["reasons"]:
            for reason in last["result"]["reasons"]:
                st.write("- " + reason)
        else:
            st.write("All applicable checks passed.")

    st.markdown("#### Open paper positions")
    if portfolio["open_positions"]:
        st.dataframe(pd.DataFrame(portfolio["open_positions"]), use_container_width=True, hide_index=True)
        with st.form("position_update_form"):
            assets = [p["asset"] for p in portfolio["open_positions"]]
            selected = st.selectbox("Position", assets)
            mark_price = st.number_input("Latest/reference price (USD)", min_value=0.00000001, value=float(next(p["last_price_usd"] for p in portfolio["open_positions"] if p["asset"] == selected)), format="%.8f")
            update_mark = st.form_submit_button("Update simulated market price")
            close_position = st.form_submit_button("Close paper position at this price")
        if update_mark:
            for position in portfolio["open_positions"]:
                if position["asset"] == selected:
                    position["last_price_usd"] = mark_price
            st.success("Paper mark price updated.")
        if close_position:
            trade = paper_exit(portfolio, selected, mark_price)
            st.success(f"Paper position closed. Realized P&L: ${trade['realized_pnl_usd']:.2f}")
    else:
        st.info("No open paper positions.")

    st.markdown("#### Closed paper trades")
    if portfolio["closed_trades"]:
        st.dataframe(pd.DataFrame(portfoliý½l±½Í}ÑÉÌt¤°ÕÍ}½¹Ñ¥¹É}Ý¥Ñ õQÉÕ°¡¥}¥¹àõQÉÕ¤(±Íè(ÍÐ¹ÁÑ¥½¸ 9¼±½ÍÑÉÌåÐ¸¤((ÍÐ¹ÁÑ¥½¸ (I¥Í¬Õ±ÑÌèÄÍ É¥Í¬ÕÐÁÈÑÉ°µàÄÀÁ½Í¥Ñ¥½¸Í¥é°(µàÈÔÉÑ½Á¸áÁ½ÍÕÉ°À¸ÄÀ¹À¸ÌÀÙÉÍÍ±¥ÁÁÁÈÍ¥¸(1ÈÕÉÉ¹Ñ±ä±¥ÙÌ¥¸Ñ¡¥ÌMÑÉµ±¥ÐÉ½ÝÍÈÍÍÍ¥½¸ìáÁ½ÉÐ½ÁÉÍ¥ÍÑ¹ÐÍÑ½É¥Ì¹áÐÍÑÀ¸(¤(¥ÍÐ¹ÕÑÑ½¸ IÍÐÙ¥ÉÑÕ°Á½ÉÑ½±¥¼Ñ¼àÀ¤è(ÍÐ¹ÍÍÍ¥½¹}ÍÑÑ¹ÁÁÉ}Á½ÉÑ½±¥¼ô¹Ý}Á½ÉÑ½±¥¼¡MQIQ%9}A%Q1}UM¤(ÍÐ¹ÍÍÍ¥½¹}ÍÑÑ¹Í­}±ÍÑ}ÉÍÕ±Ðô9½¹(ÍÐ¹ÉÉÕ¸ ¤