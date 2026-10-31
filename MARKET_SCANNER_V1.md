# Market Scanner v1

Standalone Binance Spot market scanner with a separate $80 paper portfolio. It reuses the existing deterministic trading engine in `trading_desk.py`; it does not add exchange order execution, wallet access, or private API credentials.

## What it does

- Keeps BTC, ETH, SOL, LINK, XLM, SUI and HYPE on the priority watchlist.
- Discovers liquid USDT spot markets from Binance public endpoints.
- Filters out stablecoin quote bases and leveraged-token suffixes.
- Analyses closed 1h, 4h and 1d candles with EMA20/50, RSI14, MACD histogram, ATR% and relative volume.
- Ranks candidates using deterministic scoring.
- Automatically opens a paper LONG only when the score is at least 80 and all hard checks pass.
- Marks scanner-owned paper positions and invokes the existing stop-loss/take-profit engine.
- Stores scanner state, runs, candidates and signals in separate Supabase tables.

The scanner portfolio is intentionally separate from the dashboard's existing paper portfolio. This avoids concurrent writes to the dashboard singleton and prevents scanner activity from silently overwriting manual paper trades. Both portfolios reuse `trading_desk.py` for sizing, costs, entry, exit and P&L.

## Setup

1. Run `supabase/market_scanner_v1.sql` once in the Supabase SQL Editor.
2. Deploy this repository as a separate always-on worker using `Dockerfile.scanner`.
3. Set these environment variables in the worker host:

```text
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SCANNER_INTERVAL_SECONDS=300
SCANNER_TOP_UNIVERSE_SIZE=30
SCANNER_MAX_CANDIDATES=20
SCANNER_MIN_QUOTE_VOLUME_USDT=10000000
SCANNER_MIN_SCORE=65
SCANNER_AUTO_ENTRY_SCORE=80
SCANNER_STOP_LOSS_PCT=3
SCANNER_TAKE_PROFIT_PCT=6
SCANNER_MAX_OPEN_POSITIONS=3
SCANNER_MAX_DAILY_LOSS_USDT=2.4
```

4. Configure exactly one worker replica. The database lease prevents overlapping cycles, but one replica is the intended deployment.
5. Keep the service-role key in host secrets only. Never add it to GitHub or the Streamlit browser.

## Risk and operating assumptions

- Spot-only data; scanner opens LONG paper positions only. The existing engine's SHORT support is not used here.
- The scanner uses an independent USD 80 virtual portfolio.
- Existing sizing limits, fees and slippage in `trading_desk.py` remain authoritative.
- Initial scanner stop-loss and take-profit defaults are 3% and 6%; adjust only after backtesting.
- At most three open scanner positions and a daily realized-loss stop of USD 2.40.
- A signal is keyed by symbol, closed 1h candle close time and direction to prevent repeat entries from the same candle.
- The scanner ignores the currently forming candle.
- It does not place live orders. There is no authenticated Binance client in this service.

## Notes

The scanner persists to dedicated tables; it does not write to `paper_trading_state`. Dashboard integration for viewing the scanner sub-portfolio is a later UI task. Market data and indicator thresholds are initial hypotheses, not evidence of profitability.
