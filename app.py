import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone

from trading_desk import (
    Signal, evaluate_signal, new_portfolio, paper_entry, paper_exit,
    portfolio_summary, update_position_mark, STARTING_CAPITAL_USD,
)
from supabase_store import SupabasePaperStore, SupabaseStoreError
from scanner.store import ScannerStore, ScannerStoreError
from global_markets.crypto_feed import CryptoWatchlistFeed
from global_markets.market_analysis import analyze_feed, analyze_candles
from global_markets.providers.financialdata import FinancialDataClient, FinancialDataError
    AlphaVantageClient, AlphaVantageError,
    AlphaVantageClient, AlphaVantageError, AlphaVantageRateLimitError,
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

# Refresh the whole dashboard once per minute. Market requests are cached slightly
# less than 60 seconds so each rerun can obtain a fresh quote without a timing race.
st_autorefresh(interval=60_000, limit=None, key="market-data-auto-refresh")
st.caption("Market data and open paper-position marks refresh automatically every 60 seconds. Stop-loss and take-profit checks run on each fresh quote.")

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
            "24h Volume USD": quote.get("volume_24h"),
            "Updated": quote.get("last_updated"), "Source": "CoinMarketCap",
        })
    return rows

@st.cache_data(ttl=55)
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

@st.cache_data(ttl=300)
def get_global_crypto_analysis():
    feed = CryptoWatchlistFeed()
    raw = feed.fetch(intervals=("1d", "4h"), limit=120)
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
    analyses, unavailable = [], []
    for asset_class, instruments in seeds.items():
        for symbol, international in instruments:
            try:
                rows = client.fetch_daily_prices(
                    symbol, asset_class, international=international, limit=120
                )
                result = analyze_candles(rows, max_age_seconds=5 * 86400)
                result["asset_class"] = asset_class
                result["symbol"] = symbol
                analyses.append(result)
            except (FinancialDataError, ValueError) as error:
                unavailable.append({
                    "asset_class": asset_class, "symbol": symbol,
                    "reason": str(error),
                })
    return {
        "source": "FinancialData.Net", "observed_at": datetime.now(timezone.utc).isoformat(),
        "analyses": analyses, "unavailable": unavailable,
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


latest_crypto_prices = {}
market_tab, desk_tab, global_tab, scanner_tab = st.tabs([
    "Market dashboard", "AI Crypto Trading Desk", "Global opportunity scanner", "Market Scanner"
])
with market_tab:
    st.caption("Checked at " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    st.subheader("Crypto - CoinMarketCap")
    try:
        crypto_rows = get_crypto(cmc_key)
        latest_crypto_prices = {row["Asset"]: row["Price USD"] for row in crypto_rows if row.get("Price USD")}
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
    if not paper_store:
        st.warning("Supabase is not configured: this session is temporary and will not provide a durable 30-day journal. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Streamlit Secrets.")
    else:
        st.caption("Persistent paper ledger connected to Supabase.")
        # Refresh open major-asset positions from the current CoinMarketCap snapshot.
        for open_position in list(portfolio["open_positions"]):
            current_price = latest_crypto_prices.get(open_position["asset"].upper())
            if current_price and abs(float(current_price) - float(open_position["last_price_usd"])) > 1e-12:
                stopped_trade = update_position_mark(portfolio, open_position["asset"], float(current_price))
                event = {"event_type": stopped_trade["exit_reason"] if stopped_trade else "market_mark", "asset": open_position["asset"], "price_usd": float(current_price), "trade": stopped_trade}
                try:
                    paper_store.save_state(portfolio, event)
                    if stopped_trade:
                        st.warning("Automatic {} triggered by latest CMC price for {}.".format(stopped_trade["exit_reason"].replace("_", " "), open_position["asset"]))
                except SupabaseStoreError as error:
                    st.error("Could not persist market update: " + str(error))
                    st.stop()
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
    st.write("Scout: signal intake -> Filter: hard rules -> Analyst: risk review -> Sniper: simulated entry -> Guard: automatic stop-loss, take-profit and exposure controls.")
    st.caption("First increment: candidates and Solana on-chain metrics are entered manually. The 640-wallet scanner and automated holder/bundle analytics are not connected.")

    direction = st.selectbox("Direction", ["long", "short"], format_func=lambda value: "Long (profit if price rises)" if value == "long" else "Short (profit if price falls)")
    market = st.selectbox("Market", ["major", "solana"],
        format_func=lambda value: "BTC / ETH / major altcoins" if value == "major" else "Solana tokens / memecoins")
    if market == "major":
        asset = st.selectbox("Asset", ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"])
        price = latest_crypto_prices.get(asset)
        if price and float(price) > 0:
            st.metric("CoinMarketCap reference price (USD)", "{:,.8f}".format(float(price)))
        else:
            st.error("No valid live CoinMarketCap price is available for this asset. Refresh market data before opening a paper position.")
        volume = st.number_input("24h volume (USD)", min_value=0.0, value=10000000.0, step=100000.0)
        gain45 = st.number_input("45-minute gain (%) if known; enter 0 if unavailable", min_value=-100.0, max_value=1000.0, value=0.0)
    else:
        asset = st.text_input("Token symbol or identifier", placeholder="e.g. TOKEN")
        price = st.number_input("Reference price (USD)", min_value=0.00000001, value=1.0, format="%.8f")
        liquidity = st.number_input("Liquidity (USD)", min_value=0.0, value=50000.0, step=1000.0)
        top10 = st.number_input("Top-10 holder concentration (%)", min_value=0.0, max_value=100.0, value=25.0)
        dev = st.number_input("Developer wallet share (%)", min_value=0.0, max_value=100.0, value=2.0)
        bundled = st.selectbox("Bundled buys in first 60 seconds?", [False, True])
        gain45 = st.number_input("Price gain in last 45 minutes (%)", min_value=-100.0, max_value=1000.0, value=12.0)
        source_sold = st.selectbox("Source wallet already sold?", [False, True])

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

    submitted = st.button("Run filters and simulate entry", disabled=not (price and float(price) > 0))
    if submitted:
        if market == "major":
            signal = Signal(asset=asset, market=market, price_usd=float(price),
                volume_24h_usd=volume, gain_45m_pct=gain45, source="CoinMarketCap live quote")
        else:
            signal = Signal(asset=asset, market=market, price_usd=price,
                liquidity_usd=liquidity, top10_holder_pct=top10, dev_wallet_pct=dev,
                bundled_buys_first_60s=bundled, gain_45m_pct=gain45,
                source_wallet_sold=source_sold, source="manual / on-chain metrics")

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
            if paper_store:
                paper_store.save_state(portfolio, {"event_type": stopped_trade["exit_reason"] if stopped_trade else "manual_mark", "asset": selected, "price_usd": mark_price, "trade": stopped_trade})
            if stopped_trade:
                st.warning("Automatic {} triggered. Simulated exit P&L: USD {:.2f}".format(stopped_trade["exit_reason"].replace("_", " "), stopped_trade["realized_pnl_usd"]))
            else:
                st.success("Paper mark price updated.")
        if close_position:
            trade = paper_exit(portfolio, selected, mark_price)
            if paper_store:
                paper_store.save_state(portfolio, {"event_type": "manual_exit", "asset": selected, "trade": trade})
            st.success("Paper position closed. Realized P&L: USD {:.2f}".format(trade["realized_pnl_usd"]))
    else:
        st.info("No open paper positions.")

    st.markdown("#### Closed paper trades")
    if portfolio["closed_trades"]:
        st.dataframe(pd.DataFrame(portfolio["closed_trades"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No closed trades yet.")

    st.caption("Long/short simulation enabled. Risk defaults: 1% cash risk budget per trade, 10% stop-loss, 20% take-profit, max 10% position size, max 25% aggregate open exposure, 0.10% fee and 0.30% adverse slippage per side.")
    if paper_store:
        st.markdown("#### 30-day paper-trading journal")
        try:
            recent_events = paper_store.load_events(days=30)
            if recent_events:
                st.dataframe(pd.DataFrame(recent_events), use_container_width=True, hide_index=True)
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
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Valid series", global_report["eligible_series"])
            c2.metric("Rejected series", global_report["rejected_series"])
            c3.metric("Symbols with valid data", len({row["symbol"] for row in eligible}))
            c4.metric("Unavailable requests", len(global_report["provider_unavailable"]))
            st.caption("Data source: {} | Feed timestamp: {}".format(
                global_report.get("source"), global_report.get("observed_at")))

            tactical = [row for row in eligible if row["interval"] == "4h"]
            daily = [row for row in eligible if row["interval"] == "1d"]
            if tactical:
                st.markdown("#### Tactical ranking - 4 hours")
                tactical_rows = []
                for row in tactical:
                    ind = row["indicators"]
                    tactical_rows.append({
                        "Symbol": row["symbol"],
                        "Price": row["latest_close"],
                        "RSI 14": ind["rsi_14"],
                        "MACD": ind["macd_12_26"],
                        "MACD signal": ind["macd_signal_9"],
                        "SMA 20": ind["sma_20"],
                        "SMA 50": ind["sma_50"],
                        "Volatility %": ind["realized_volatility_pct_annualized_approx"],
                        "Technical score": row["technical_screen_score"],
                        "Age (min)": round(row["age_seconds"] / 60, 1),
                    })
                tactical_rows.sort(key=lambda item: item["Technical score"], reverse=True)
                st.dataframe(pd.DataFrame(tactical_rows), use_container_width=True, hide_index=True)

            if daily:
                st.markdown("#### Trend confirmation - daily")
                daily_rows = []
                for row in daily:
                    ind = row["indicators"]
                    daily_rows.append({
                        "Symbol": row["symbol"], "Price": row["latest_close"],
                        "RSI 14": ind["rsi_14"], "MACD": ind["macd_12_26"],
                        "MACD signal": ind["macd_signal_9"], "SMA 20": ind["sma_20"],
                        "SMA 50": ind["sma_50"],
                        "Technical score": row["technical_screen_score"],
                        "Age (h)": round(row["age_seconds"] / 3600, 1),
                    })
                daily_rows.sort(key=lambda item: item["Technical score"], reverse=True)
                st.dataframe(pd.DataFrame(daily_rows), use_container_width=True, hide_index=True)

            aligned = global_report.get("cross_timeframe", [])
            if aligned:
                st.markdown("#### Multi-timeframe alignment - daily 60% + 4h 40%")
                st.caption("Only symbols with both fresh, closed intervals are included. Scores combine the existing technical screening scores; they are not expected returns or trade signals.")
                alignment_rows = [{
                    "Symbol": row["symbol"],
                    "Daily score": row["daily_score"],
                    "4h score": row["4h_score"],
                    "Alignment score": row["alignment_score"],
                    "Bias": row["stance"],
                } for row in aligned]
                st.dataframe(pd.DataFrame(alignment_rows), use_container_width=True, hide_index=True)

            if rejected:
                st.markdown("#### Rejected data series")
                st.dataframe(pd.DataFrame([{
                    "Symbol": row.get("symbol"), "Interval": row.get("interval"),
                    "Bars": row.get("bars"), "Age (seconds)": row.get("age_seconds"),
                    "Reasons": ", ".join(row.get("reasons", [])),
                } for row in rejected]), use_container_width=True, hide_index=True)

            if global_report["provider_unavailable"]:
                st.markdown("#### Provider unavailable")
                st.dataframe(pd.DataFrame(global_report["provider_unavailable"]),
                    use_container_width=True, hide_index=True)

            st.caption("Technical score is a screening indicator based on trend, MACD, moving averages and RSI. It is not a probability, expected return or investment recommendation. Fundamental and catalyst coverage is not yet included.")
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
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                if bad:
                    st.markdown("#### Rejected histories")
                    st.dataframe(pd.DataFrame([{
                        "Asset class": item.get("asset_class"), "Symbol": item.get("symbol"),
                        "Reasons": ", ".join(item.get("reasons", [])),
                    } for item in bad]), use_container_width=True, hide_index=True)
                if daily_report["unavailable"]:
                    st.markdown("#### Provider unavailable / no exact symbol data")
                    st.dataframe(pd.DataFrame(daily_report["unavailable"]),
                        use_container_width=True, hide_index=True)
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
                    st.dataframe(pd.DataFrame(fx_rows), use_container_width=True, hide_index=True)
                if rejected:
                    st.markdown("#### Rejected FX histories")
                    st.dataframe(pd.DataFrame([{
                        "Pair": item.get("symbol"), "Reasons": ", ".join(item.get("reasons", [])),
                    } for item in rejected]), use_container_width=True, hide_index=True)
                if fx_report["unavailable"]:
                    st.markdown("#### FX provider unavailable")
                    st.dataframe(pd.DataFrame(fx_report["unavailable"]), use_container_width=True, hide_index=True)
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
                    st.dataframe(pd.DataFrame(scanner_state["open_positions"]), use_container_width=True, hide_index=True)
                if scanner_state.get("closed_trades"):
                    st.markdown("#### Scanner closed paper trades")
                    st.dataframe(pd.DataFrame(scanner_state["closed_trades"][-50:]), use_container_width=True, hide_index=True)
            else:
                st.info("The scanner has not completed its first cycle yet.")
            st.markdown("#### Latest market candidates")
            if scanner_candidates:
                st.dataframe(pd.DataFrame(scanner_candidates), use_container_width=True, hide_index=True)
            else:
                st.info("No scanner candidates stored yet.")
        except (ScannerStoreError, ValueError) as error:
            st.error("Could not load Market Scanner data: " + str(error))
