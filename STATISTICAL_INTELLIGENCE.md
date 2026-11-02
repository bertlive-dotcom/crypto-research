# Statistical Intelligence prototype

This prototype is an isolated research tool. It does **not** modify the Market Scanner, paper portfolio, open positions, entry thresholds, or execution logic.

## Run

From the repository root:

```bash
python tools/run_statistical_research.py
python tools/run_breakout_retest_research.py --limit 1000
python tools/run_contextual_statistics.py --limit 1000
```

The daily tools read public Binance Spot daily candles. The contextual tool reads public Binance Spot hourly candles. No API key, exchange account, or order permission is used.

## Hourly contextual statistics

The separate `tools/run_contextual_statistics.py` runner analyzes closed 1-hour candles for BTC, ETH and SOL by default. Override the universe with `--symbols`.

It groups forward close-to-close returns over 1, 3, 6 and 12 hours by:
- UTC hour of day and UTC weekday.
- Trailing trend regime (bullish, bearish, sideways/transition), based on SMA50 level and slope versus 10 hours earlier.
- Trailing realized volatility (high/low versus the median of the prior 180 rolling 20-hour volatility observations).
- Combined trend/volatility regime.

Each group reports mean, median, positive-return percentage, observation count and excess versus the matching unconditional baseline. Results are separated into the first 70% exploration period and final 30% chronological holdout.

Important limits:
- UTC buckets are not exchange-session labels or local time.
- The public Binance endpoint currently limits each request to 1,000 candles, about 41 days at 1h. This is a short sample; pagination is needed for robust seasonality conclusions.
- Forward returns overlap, so observations are not independent.
- Minimum 30 observations is only an exploratory label, not proof of significance.
- No fees, spread, slippage, funding, execution or market impact are modeled.
- This is descriptive research only; no trade signals are produced.

## Breakout-retest candidate

The separate `tools/run_breakout_retest_research.py` runner tests a daily breakout followed by a retest. Its default research universe is BTC, ETH, SOL, DOGE, BONK, WIF, PUMP, UNI, NEAR, ZEC, AAVE and PEPE (USDT spot pairs). Override this list with `--symbols`.

- A breakout candle must close beyond the previous daily high/low and pass EMA50/EMA200, RSI, MACD and relative-volume filters.
- The retest must occur in one of the next three candles. It must trade within 0.25 ATR of the breakout level, then close back beyond that level in the breakout direction with a directional candle body.
- A close more than 0.25 ATR through the level invalidates the setup. No retest by the end of the window means no trade.
- Entry is the next candle open after the retest confirmation; the retest candle itself is never used as the entry.
- Stop is beyond the retest candle extreme and a 0.5 ATR buffer from the breakout level. Target is 2R; maximum holding time is five daily candles.
- Baseline costs are 0.10% fee and 0.05% slippage per side (0.30% round trip).
- If a candle opens through the stop, the simulation exits at that worse opening price. If stop and target are both touched intraday, stop is assumed first.

The script reports exploration (first 70%) and chronological holdout (final 30%) separately. A minimum of 30 trades is only an exploratory sample label, not proof of statistical significance.

## Interpretation and limits

- These are descriptive historical results, **not predictive probabilities or trade recommendations**.
- Daily OHLC cannot reveal the intraday path. Gap stops are approximated at the opening price; additional spread and market impact are not modeled.
- Funding, partial fills and changing fees/slippage are not modeled.
- Small holdout samples do not establish an edge. Do not select a strategy based on the exploration segment alone.
- All studies are research-only. They are not connected to Market Scanner scoring, paper trading, open positions, thresholds or execution logic.
- Expanded-universe breakout-retest snapshot for 2026-11-02: `reports/breakout_retest_expanded_universe_2026-11-02.json`. Different listing dates mean unequal sample windows; PUMP has materially less history.
