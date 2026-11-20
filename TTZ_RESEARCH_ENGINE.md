# TTZ-inspired research engine

## Scope
This increment reproduces four general price-action concepts described in the TTZ promotion. It is an independent heuristic implementation, not a copy of TTZ source code and not evidence that its proprietary indicator uses the same formulas.

The engine is research-only. Its outputs are attached to each timeframe feature record and do not affect candidate scores, hard gates, automatic paper-entry eligibility, portfolio risk rules or execution.

## Inputs and timing
- OHLCV candles from the existing Binance Spot scanner.
- The existing scanner excludes the newest potentially forming candle before feature calculation.
- Diagnostics are calculated independently for 1h, 4h and 1d.
- A minimum of 22 closed candles is needed for the default 20-candle range lookback plus breakout context.
- Missing or invalid data fails closed with `INSUFFICIENT_DATA`.

## Heuristic definitions
- Wick rejection: upper or lower wick occupies at least 45% of the candle range and the close is in the corresponding half of the range.
- Failed high/low: price trades beyond the preceding 20-candle high/low but closes back inside the prior range.
- Retest: the previous candle closes beyond a range level; the current candle revisits within 0.30% and closes back on the breakout side.
- Exhaustion: a wick rejection occurs with current volume at least 1.5 times the average of up to 20 preceding candles. The output is labelled UPSIDE or DOWNSIDE exhaustion, not a reversal forecast.

These thresholds are initial research parameters. They are not calibrated and must be tested across different assets and regimes.

## Output
Each timeframe feature record receives a `ttz` object:
- `status`
- `lookback`
- `range_high`, `range_low`
- `wick_rejection`
- `failed_breakout`
- `retest`
- `exhaustion`
- `volume_ratio`

## Validation plan
1. Run `python -m unittest discover -s tests -p 'test_ttz_price_action.py' -v`.
2. Run the full suite: `python -m unittest discover -s tests -v`.
3. Compare the existing scanner with and without TTZ diagnostics on identical closed-candle datasets.
4. Backtest each signal family separately and combined, net of fees and slippage.
5. Use out-of-sample periods and a forward paper-trading period; report sample size, expectancy, profit factor, win rate and maximum drawdown.
6. Do not connect these diagnostics to automatic entries until a separate review approves their incremental value and risk impact.

## Limitations
- This is not the TTZ proprietary indicator and does not establish equivalence.
- OHLCV cannot reconstruct the tick path inside a candle.
- A wick or failed breakout is descriptive and may fail repeatedly in trending markets.
- Backtest performance can be distorted by repainting, lookahead, selection bias and overfitting.
