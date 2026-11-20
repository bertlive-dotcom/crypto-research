

## Portfolio-level Prop-Firm Risk Guard (experimental branch)
The standalone Market Scanner adds an outer portfolio guard before new paper entries. It reuses the existing portfolio JSON state; no new Supabase table or secret is required.
- Daily loss: 2% of initial virtual capital, measured from UTC day-start equity (realized plus marked open-position equity). A breach blocks new entries until the next UTC day.
- Trailing drawdown: 6% of initial virtual capital measured from the highest observed portfolio equity. A breach is latched and permanently blocks new entries in this paper account.
- Aggregate floating loss: 2% of initial virtual capital, using estimated unrealized P&L after the paper engine's fee/slippage assumptions. A breach blocks new entries while the threshold remains breached.
- Existing positions continue to be marked and their stop-loss/take-profit logic remains active; this guard does not force-close positions.
- The first run initializes day-start equity and high-water equity from the currently observed portfolio equity. It cannot reconstruct an earlier high-water mark from history not stored in the portfolio state.
- The guard applies to the standalone Market Scanner worker, not the separate interactive AI Trading Desk session portfolio.
- The guard is experimental and is not deployed until tests, staging verification and review are complete. It is not a profitability claim or a live-trading feature.
