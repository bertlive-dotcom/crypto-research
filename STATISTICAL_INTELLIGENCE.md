# Statistical Intelligence prototype

This prototype is an isolated research tool. It does **not** modify the Market Scanner, paper portfolio, open positions, entry thresholds, or execution logic.

## Run

From the repository root:

```bash
python tools/run_statistical_research.py
python tools/run_breakout_retest_research.py --limit 1000
```

Both tools read public Binance Spot daily candles. No API key, exchange account, or order permission is used.

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
- The retest study is research-only. It is not connected to Market Scanner scoring, paper trading, open positions, thresholds or execution logic.\n- Expanded-universe snapshot for 2026-11-02: `reports/breakout_retest_expanded_universe_2026-11-02.json`. Different listing dates mean unequal sample windows; PUMP has materially less history.
