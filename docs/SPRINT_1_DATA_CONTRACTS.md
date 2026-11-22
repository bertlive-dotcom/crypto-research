# Sprint 1 data contracts

## Binance Spot kline timestamps

The scanner consumes the Binance Spot `GET /api/v3/klines` array format:

- `[0]`: candle open time, Unix milliseconds UTC.
- `[1..5]`: open, high, low, close and base-asset volume.
- `[6]`: candle close time, Unix milliseconds UTC.

The scanner deliberately excludes the final, still-forming kline from indicators. Each feature record therefore carries both `candle_open_time` and `candle_close_time` from the last completed kline. These values are milliseconds, not seconds, and are not interchangeable. Missing close-time metadata is treated as unverified; the six-stage pipeline rejects a candidate without a closed-candle timestamp.

## `change_pct` and `gain_1h_pct`

For a timeframe feature record, `change_pct` is:

```text
((latest_closed_close / previous_closed_close) - 1) * 100
```

It is a percentage number, not a decimal fraction: `2.0` means +2.0%, and `-1.5` means -1.5%. For the one-hour feature record this value is passed unchanged to `Signal.gain_1h_pct`.

The major-asset signal contract is:

- `gain_1h_pct`: percentage return across the two most recent completed 1h candles.
- `volume_24h_usd`: 24-hour quote volume in USD/USDT units.
- Missing 1h gain or 24h volume fails closed.
- The current major-asset rule rejects `gain_1h_pct > 80`; it does not reject negative gains.
- Do not populate `gain_1h_pct` with 45-minute, 24-hour, or decimal-fraction returns.

`trading_desk.evaluate_signal` retains a legacy fallback from `gain_45m_pct` only for old callers. New scanner and agent code must always supply `gain_1h_pct`; the fallback should be removed only after all external/legacy callers and persisted payloads have been audited.

## Paper SL/TP candle evaluation

The scanner worker evaluates each open position against the latest completed 5-minute Binance candle (the penultimate row returned by a two-row kline request). It no longer assumes a sampled ticker quote proves that no stop/target was crossed between worker cycles.

- If both stop and take-profit are crossed within one candle, stop-loss wins (conservative ambiguity rule).
- If the candle opens beyond the stop, the simulated stop fill uses the worse candle open.
- Take-profit fills at the target threshold; no favorable gap improvement is assumed.
- A missing or malformed candle does not close the position; the worker logs and retries on the next cycle.
- This is an OHLC approximation, not tick-level execution or evidence of real-market fills.

## Regression coverage

Relevant tests: `tests/test_market_scanner.py`, `tests/test_trading_desk.py`, and `tests/test_six_agent_pipeline.py`.
