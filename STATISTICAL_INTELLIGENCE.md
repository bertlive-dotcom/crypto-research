# Statistical Intelligence prototype

This prototype is an isolated research tool. It does **not** modify the Market Scanner, paper portfolio, open positions, entry thresholds, or execution logic.

## Run

From the repository root:

```bash
python tools/run_statistical_research.py
```

Optional:

```bash
python tools/run_statistical_research.py --symbols BTCUSDT ETHUSDT SOLUSDT --limit 1000 --output statistical_research_report.json
```

It reads public Binance Spot daily candles and writes a JSON report. No API key, exchange account, or order permission is used.

## What it measures

- Inside bars: unsigned close-to-close returns after the pattern.
- Bullish and bearish engulfing candles: direction-adjusted close-to-close returns.
- Previous-day range breakouts: direction-adjusted close-to-close returns after a daily close beyond the previous candle's high or low.
- Forward horizons: 1, 3 and 5 daily candles by default.
- Occurrence counts, mean return, median return, positive-outcome percentage, and a small-sample warning.\n- Trend-regime breakdown (bullish, bearish, sideways/transition) using a 50-day SMA and its 10-day direction.\n- Pattern returns compared with a matched unconditional candle-return baseline in the same regime, including excess return in percentage points.

A minimum sample of 30 observations is used only as an exploratory label, not as proof of statistical significance.

## Interpretation and limits

- These are descriptive historical conditional outcomes, **not predictive probabilities or trade recommendations**.
- Outcomes are measured from the pattern candle close. They do not model executable entries, fees, slippage, stop-losses, take-profits, or position sizing.
- Overlapping events are retained and are not independent observations.\n- Regime labels use only information available at the event candle close; the 50-day SMA needs 60 candles of warm-up. Regime comparison remains descriptive and is not a significance test.
- Daily bars do not test intraday session behaviour.
- A 1,000-candle Binance request is a finite history window; it is not equivalent to Edgeful's longer historical database.
- The prototype deliberately does not feed results into Market Scanner scoring or paper trading.

## Validation sequence

1. Run the script for BTCUSDT, ETHUSDT and SOLUSDT.
2. Inspect event counts and sample warnings before interpreting returns.
3. Compare 1-, 3- and 5-day results; look for stability rather than the best single percentage.
4. Split the history chronologically into an exploratory period and a later holdout period before treating any pattern as potentially useful.
5. Only after independent validation consider adding a read-only research panel to the dashboard. Do not convert these metrics into entry gates without a separate decision and paper test.
