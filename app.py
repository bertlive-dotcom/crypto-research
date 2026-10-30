import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone

from trading_desk import (
    Signal, evaluate_signal, new_portfolio, paper_entry, paper_exit,
    portfolio_summary, update_position_mark, STARTING_CAPITAL_USD,
)

st.set_page_config(page_title="Crypto & Equities", layout="wide")
st.title("Crypto & Equities Dashboard")

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

@st.cache_data(ttl=60)
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
            "24h Volume USD": quote.get("volume_24h"),
            "Updated": quote.get("last_updated"), "Source": "CoinMarketCap",
        })
    return rows

@st.cache_data(ttl=60)
def get_quote(symbol, key):
    response = requests.get("https://api.twelvedata.com/quote",
        params={"symbol": symbol, "apikey": key}, timeout=15)
    response.raise_for_status()
    data = response.json()
    if data.get("status") == "error" or "code" in data:
        raise RuntimeError(data.get("message", "Twelve Data error"))
    price = data.get("close") or data.get("price")
    return {
        "Asset": symbol, "Price USD": float(price) if price else None,
        "24h %": float(data["percent_change"]) if data.get("percent_change") else None,
        "Updated": data.get("datetime"), "Source": "Twelve Data",
    }

if st.button("Refresh market data"):
    get_crypto.clear()
    get_quote.clear()

market_tab, desk_tab = st.tabs(["Market dashboard", "AI Crypto Trading Desk"])
with market_tab:
    st.caption("Checked at " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    st.subheader("Crypto - CoinMarketCap")
    try:
        crypto_rows = get_crypto(cmc_key)
        st.dataframe(pd.DataFrame(crypto_rows), use_container_width=True, hide_index=True)
    except Exception as error:
        st.error("CMC request failed: " + str(error))
    st.subheader("Stocks and ETFs - Twelve Data")
    symbols = st.multiselect("Symbols",
        ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "SPY", "QQQ"],
        ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"])
    rows = []
    for symbol in symbols:
        try:
            rows.append(get_quote(symbol, twelve_key))
        except Exception as error:
            st.warning(symbol + ": " + str(error))
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Informational market snapshots only. No trade execution.")

with desk_tab:
    st.subheader("Paper Trading - virtual capital")
    st.warning("SIMULATION ONLY. No exchange orders, wallet connections, or real funds are used.")
    if "paper_portfolio" not in st.session_state:
        st.session_state.paper_portfolio = new_portfolio(STARTING_CAPITAL_USD)
    if "desk_last_result" not in st.session_state:
        st.session_state.desk_last_result = None

    portfolio = st.session_state.paper_portfolio
    summary = portfolio_summary(portfolio)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Virtual equity", "USD {:.2f}".format(summary["equity_usd"]))
    col2.metric("Cash available", "USD {:.2f}".format(summary["cash_usd"]))
    col3.metric("Realized P&L", "USD {:.2f}".format(summary["realized_pnl_usd"]))
    col4.metric("Unrealized P&L", "USD {:.2f}".format(summary["unrealized_pnl_usd"]))
    st.caption("Starting capital: USD {:.2f} | Return: {:.2f}% | Open: {} | Closed: {}".format(
        portfolio["starting_capital"], summary["total_return_pct"],
        summary["open_positions"], summary["closed_trades"]))

    st.markdown("#### Five-agent pipeline")
    st.write("Scout: signal intake -> Filter: hard rules -> Analyst: risk review -> Sniper: simulated entry -> Guard: stop-loss and exposure controls.")
    st.caption("First increment: candidates and Solana on-chain metrics are entered manually. The 640-wallet scanner and automated holder/bundle analytics are not connected.")

    with st.form("signal_form"):
        market = st.selectbox("Market", ["major", "solana"],
            format_func=lambda value: "BTC / ETH / major altcoins" if value == "major" else "Solana tokens / memecoins")
        if market == "major":
            asset = st.selectbox("Asset", ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"])
        else:
            asset = st.text_input("Token symbol or identifier", placeholder="e.g. TOKEN")
        price = st.number_input("Reference price (USD)", min_value=0.00000001, value=1.0, format="%.8f")
        stop_pct = st.slider("Stop Loss (%)", min_value=1, max_value=30, value=10)
        if market == "major":
            volume = st.number_input("24h volume (USD)", min_value=0.0, value=10000000.0, step=100000.0)
            gain45 = st.number_input("45-minute gain (%) if known; enter 0 if unavailable", min_value=-100.0, max_value=1000.0, value=0.0)
            submitted = st.form_submit_button("Run filters and simulate entry")
            if submitted:
                signal = Signal(asset=asset, market=market, price_usd=price,
                    volume_24h_usd=volume, gain_45m_pct=gain45, source="manual / CMC cross-check")
        else:
            liquidity = st.number_input("Liquidity (USD)", min_value=0.0, value=50000.0, step=1000.0)
            top10 = st.number_input("Top-10 holder concentration (%)", min_value=0.0, max_value=100.0, value=25.0)
            dev = st.number_input("Developer wallet share (%)", min_value=0.0, max_value=100.0, value=2.0)
            bundled = st.selectbox("Bundled buys in first 60 seconds?", [False, True])
            gain45 = st.number_input("Price gain in last 45 minutes (%)", min_value=-100.0, max_value=1000.0, value=12.0)
            source_sold = st.selectbox("Source wallet already sold?", [False, True])
            submitted = st.form_submit_button("Run filters and simulate entry")
            if submitted:
                signal = Signal(asset=asset, market=market, price_usd=price,
                    liquidity_usd=liquidity, top10_holder_pct=top10, dev_wallet_pct=dev,
                    bundled_buys_first_60s=bundled, gain_45m_pct=gain45,
                    source_wallet_sold=source_sold, source="manual / on-chain metrics")

    if submitted:
        result = evaluate_signal(signal)
        st.session_state.desk_last_result = {"signal": signal, "result": result}
        if result["approved"]:
            try:
                position = paper_entry(portfolio, signal, stop_loss_pct=float(stop_pct))
                st.success("Signal approved. Paper position: USD {:.2f}; stop price {:.8f}.".format(
                    position["notional_usd"], position["stop_price"]))
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
        st.dataframe(pd.DataFrame(portfolio["open_positions"]), use_container_width=True, hide_index=True)
        with st.form("position_update_form"):
            assets = [position["asset"] for position in portfolio["open_positions"]]
            selected = st.selectbox("Position", assets)
            default_price = next(p["last_price_usd"] for p in portfolio["open_positions"] if p["asset"] == selected)
            mark_price = st.number_input("Latest/reference price (USD)", min_value=0.00000001, value=float(default_price), format="%.8f")
            update_mark = st.form_submit_button("Update simulated market price")
            close_position = st.form_submit_button("Close paper position at this price")
        if update_mark:
            stopped_trade = update_position_mark(portfolio, selected, mark_price)
            if stopped_trade:
                st.warning("Guard stop triggered. Simulated exit P&L: USD {:.2f}".format(stopped_trade["realized_pnl_usd"]))
            else:
                st.success("Paper mark price updated.")
        if close_position:
            trade = paper_exit(portfolio, selected, mark_price)
            st.success("Paper position closed. Realized P&L: USD {:.2f}".format(trade["realized_pnl_usd"]))
    else:
        st.info("No open paper positions.")

    st.markdown("#### Closed paper trades")
    if portfolio["closed_trades"]:
        st.dataframe(pd.DataFrame(portfolio["closed_trades"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No closed trades yet.")

    st.caption("Risk defaults: 1% cash risk budget per trade, max 10% position size, max 25% aggregate open exposure, 0.10% fee and 0.30% adverse slippage per side. Ledger is held in this Streamlit browser session and is not yet persistent.")
    if st.button("Reset virtual portfolio to USD 80"):
        st.session_state.paper_portfolio = new_portfolio(STARTING_CAPITAL_USD)
        st.session_state.desk_last_result = None
        st.rerun()
