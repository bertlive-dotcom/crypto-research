# Trading Desk audit and six-lesson course integration

Status: research/audit proposal. This document does not change scanner scoring, paper entries, position sizing, exits, thresholds, or production configuration.

## Executive conclusion

The current Market Scanner v1 is a deterministic 1h/4h/1d momentum-continuation scanner. It is not yet an implementation of the six-lesson course framework. Several course concepts are absent, and one important scoring inconsistency allows an auto-entry candidate to pass despite weak momentum confirmation.

Preferred architecture:
1. keep the current scanner as a baseline;
2. add course-derived, explainable diagnostics in parallel;
3. compare baseline vs course-confluence variants in historical research and paper mode;
4. activate a new hard gate only after out-of-sample evidence and explicit review.

Do not add indicators merely to increase the score. Aim to reduce low-quality signals and improve execution/risk discipline.

## Course lessons translated into testable rules

### Lesson 1 — Psychology and risk
- Require a written setup before entry: direction, invalidation, stop, target, risk amount and reason.
- No FOMO or late entries; never widen a stop to avoid realizing a loss.
- Risk is measured as expected loss at stop after fees/slippage, not by margin/notional.
- Preserve operating constraints: default 1% risk per trade, 2% exceptional, no more than 3 concurrent trades, pause after 3 consecutive losses, minimum planned R:R 1:2, leverage <=3x and preferably none.
- These are governance constraints, not signals to optimize.

### Lesson 2 — EMA50 and multi-timeframe trend
- Weekly EMA50: broad market direction.
- Daily structure: confirm trend and important swing levels.
- 4h: execution context, pullback/retest and invalidation.
- EMA50 is a dynamic reference only when trend structure and slope support it; a simple cross is not an entry.
- Current scanner has no weekly feed or EMA200 calculation and uses 1h EMA20/50 plus 4h/daily close above EMA20. This is materially different.

### Lesson 3 — Stochastic 14,3,3
- Use Stochastic as timing/momentum confirmation, not as an isolated overbought/oversold reversal trigger.
- Divergence is a warning, not an automatic trade.
- Current scanner does not calculate Stochastic.

### Lesson 4 — Squeeze Momentum, ADX and divergence
- ADX measures trend strength, not direction; pair it with direction/structure.
- Squeeze Momentum can be used as momentum-state confirmation.
- Divergence is a caution/quality signal.
- The exact Squeeze script/formula from the course has not been verified; do not implement a guessed variant or claim equivalence.
- Current scanner calculates MACD histogram, RSI and ATR, but not ADX or Squeeze Momentum.

### Lesson 5 — FVG, wicks and CME gaps
- FVG and wick behavior must have objective, reproducible definitions and use only candles available at decision time.
- Do not import unsupported fill-rate claims (e.g. 93%) as a strategy rule.
- CME gaps are BTC-specific context and should not be generalized to all crypto assets.
- Current scanner does not detect FVGs, rejection wicks or CME gaps.

### Lesson 6 — Historical highs/lows
- Use confirmed swing highs/lows and prior significant levels as context, not look-ahead pivots.
- A broken resistance may become support; require observable retest/acceptance rather than assuming it.
- Current scanner does not include a confirmed swing/pivot or prior-level module.

## Current code audit (main branch)

### What exists
- Binance Spot public data only; closed 1h/4h/1d candles.
- EMA20/EMA50, RSI14, MACD histogram, ATR%, relative volume.
- 1h trend: close > EMA20 > EMA50 for long candidates.
- 4h and daily confirmation: close > EMA20.
- ATR range 0.5%-8%; entry extension <=4% above 1h EMA20.
- Weighted score plus separate hard gates; automatic LONG paper entries at score >=80.
- Scanner state uses separate Supabase tables from dashboard paper ledger.
- Paper engine supports long/short, fees/slippage, position IDs, candle TP/SL and stop-first ambiguous-candle behavior.

### Material gaps / defects
1. **Momentum is only a soft score component.** hard_checks_pass does not require positive MACD histogram or RSI 48-70. An existing unit test explicitly allows an 80-point candidate to auto-enter with negative MACD histogram and RSI 40. This conflicts with the course's momentum-confirmation principle. Recommendation: preserve these as diagnostics initially; test hard-gate variants before activation.
2. **No weekly trend filter / EMA200.** Current data windows are 1h/4h/1d, each only 100 candles. A weekly EMA50 and daily EMA200 cannot be evaluated reliably with this input.
3. **No structure/pullback context.** No confirmed swing highs/lows, FVG, wick rejection, or explicit 4h retest state.
4. **No Stochastic, ADX or Squeeze Momentum.** Squeeze formula must be confirmed from course source before coding.
5. **Scanner is LONG-only.** apply_paper_rules and worker.run_once open LONG only, despite the underlying paper engine supporting SHORT. Do not add SHORT until its own filters, stop/borrow/funding assumptions and tests are validated.
6. **Fixed exits.** Scanner defaults to 3% stop and 6% target, not ATR/structure-based. Backtest ATR and structure stops in research before changing defaults.
7. **Risk-budget mismatch.** size_position targets 1% risk but the 10% notional cap plus 3% stop means maximum nominal stop risk is only 0.3% of equity before costs. This is conservative, but the UI/docs should report actual risk at stop, not label all trades as 1% risk.
8. **Daily loss guard uses realized P&L only.** It ignores open-position unrealized P&L. A risk-control improvement should consider realized + unrealized daily P&L, while handling mark freshness and UTC/session boundaries.
9. **No max holding-time or stagnation exit.** Positions can remain open until TP/SL/manual close. Evaluate time stop and volatility-adjusted exit in research only.
10. **Important existing entry-path issue on main.** The worker constructs a major-asset Signal without gain_1h_pct, while evaluate_signal requires the 1h field for manual major signals. The proposed fix is already in draft PR #17 via a source-scoped scanner_approved flag; review its CI and exact source check before merging. Do not weaken manual-signal validation.
11. **Market-data quality.** Scanner uses a public ticker and klines but has no explicit spread/quote freshness guard for entry execution beyond candle-close de-duplication. Add data-age and spread diagnostics before considering higher-frequency automation.

## Recommended implementation sequence

### Phase A — Safety and observability (first)
- Review and test PR #17 (scanner entry path, legacy TP/SL migration and stop-gap handling).
- Add explicit displayed/calculated risk-at-stop after entry/exit costs.
- Add a daily loss guard based on realized plus fresh unrealized P&L; fail closed on stale marks.
- Add scanner health metrics: last successful cycle, per-symbol candle close times, quote age, API errors, skipped reasons.
- Do not change signal thresholds in this phase.

### Phase B — Course-derived diagnostic layer (research-only)
Add an independent module that reports:
- weekly EMA50 direction and slope;
- daily EMA50/EMA200 trend and confirmed market structure;
- 4h pullback/retest state and invalidation;
- Stochastic 14,3,3;
- ADX14 (directional movement plus strength);
- objective FVG and wick/rejection descriptors;
- confirmed prior swing highs/lows and distance to level;
- Squeeze Momentum only after the exact source formula is confirmed.

These outputs should be stored beside candidates but must not change score, hard_checks_pass, auto_entry_eligible, entries, sizing or exits.

### Phase C — Paired strategy research
Compare:
- baseline scanner;
- baseline + hard momentum confirmation;
- weekly/daily trend filter;
- 4h retest confirmation;
- structure/FVG/wick confluence;
- Stochastic/ADX confirmation;
- combinations selected only in exploration.

Use the same universe, candle periods, execution timing, stops/targets, costs and risk sizing for paired comparisons. Split chronologically, reserve a truly prospective holdout, bootstrap by calendar-date blocks across assets, report long/short separately, and include drawdown, losing streaks, expectancy, PF, turnover and signal count. Correct for multiple testing; do not treat many indicators as independent evidence.

### Phase D — Controlled paper trial
- Run the best candidate beside baseline without automatic promotion.
- Compare rejected/accepted signals and execution outcomes for at least 30 days and a meaningful sample.
- Require no deterioration in drawdown and evidence of improved net expectancy after costs.
- Only then propose a separate explicit approval for changing scanner auto-entry gates.

## Acceptance criteria before activation
- Unit tests and CI green.
- No look-ahead or open-candle signals.
- No cross-split trades.
- Fees, slippage, spread and gap behavior included.
- Adequate per-side and per-regime sample sizes.
- Holdout not used for parameter selection.
- Actual risk at stop within user's limits.
- No production changes without a separate approval.

## Current decision
Keep the existing Market Scanner and paper engine unchanged. Treat the course concepts as a research overlay until Phase A safety checks and Phase C paired evidence are complete.
