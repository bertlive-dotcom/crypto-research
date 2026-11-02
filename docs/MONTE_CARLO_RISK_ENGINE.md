# Monte Carlo Risk Engine

Isolated, read-only risk research for historical strategy outcomes. It has no exchange client, API key, order permission, scanner integration, paper-ledger integration or execution path.

## Input and R normalization

The adapter accepts both the current flat report shape (`assets[].trades[]`) and the earlier nested shape (`assets[].breakout_retest.trades[]`). Each trade's net R is calculated as:

`net R = net_return_pct / (abs(entry - stop) / entry * 100)`

The breakout-retest generator records entry and stop prices in its trade rows. The expanded-universe JSON report dated 2026-11-02 predates that output change and contains only dates, side, exit reason and net return. It cannot support a valid R calculation: percentage return alone does not identify the initial price risk. The runner now labels these rows `incomplete_trade_data` and refuses to simulate them. Regenerate the source report with the current `tools/run_breakout_retest_research.py` before running Monte Carlo.

The source report's `net_return_pct` already includes its configured round-trip fee and slippage assumptions. Do not subtract costs a second time.

## Simulation methods

- IID bootstrap samples individual historical net-R outcomes with replacement.
- Moving-block bootstrap samples contiguous blocks to retain some local ordering and loss clustering.
- Both generate configurable numbers of paths and report ending equity returns, maximum drawdown, losing streaks and the frequency of crossing a configurable drawdown threshold.

Equity compounds using fixed-fractional risk per trade. The default 1% risk and 20% drawdown threshold are research assumptions, not live trading instructions.

## Run

First regenerate a source report using closed daily candles:

```bash
python tools/run_breakout_retest_research.py \
  --output reports/breakout_retest_expanded_universe_2026-11-02.json
```

Then run the Monte Carlo research:

```bash
python tools/run_monte_carlo_research.py \
  --input reports/breakout_retest_expanded_universe_2026-11-02.json \
  --output reports/monte_carlo/monte_carlo_risk_report.json
```

Optional controls: `--simulations`, `--risk-per-trade-pct`, `--block-size`, `--ruin-drawdown-pct`, and `--seed`.

The runner simulates exploration and holdout trades separately. A segment with fewer than 10 trades is reported as insufficient for simulation; 10 is only a technical floor, not evidence of statistical sufficiency. Missing entry/stop fields or invalid trade rows are reported explicitly and never silently coerced.

## Interpretation

- Monte Carlo is a sensitivity analysis of the observed trade sample, not a forecast or proof of an edge.
- IID resampling removes serial dependence. Moving blocks preserve only limited local ordering and do not model regime transitions.
- Results are sensitive to sample size, sample selection, costs, risk assumptions and structural market changes.
- Exploration results must not be presented as out-of-sample validation.
- Small holdout samples remain inconclusive even if simulated distributions look favorable.

## Safety boundary

This tool only reads research JSON and writes a separate report. It must not import or call Market Scanner, paper trading, portfolio, position, exchange trading or execution modules. No production settings or operational records are modified.
