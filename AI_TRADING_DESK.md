# AI Crypto Trading Desk - simulation-only MVP

## Scope
- Virtual starting capital: USD 80.
- Markets: Solana tokens/memecoins and major crypto assets.
- No live trading, exchange order endpoints, wallet signing, seed phrases, or private keys.
- The five roles are deterministic software stages in this MVP, not autonomous LLM agents:
  1. Scout: accepts a manually entered or externally sourced candidate signal.
  2. Filter: applies hard eligibility rules.
  3. Analyst: displays rule outcomes and risk assumptions.
  4. Sniper: opens a simulated position only.
  5. Guard: requires a stop-loss percentage and enforces position/exposure limits.

## Filters
For Solana candidates, missing on-chain inputs fail closed:
- liquidity >= USD 30,000;
- top-10 holder concentration <= 40%;
- developer wallet share <= 8%;
- no bundled buys in first 60 seconds;
- 45-minute gain <= 80%;
- source wallet has not sold.

For major assets, wallet/holder checks are not applicable. The MVP requires 24-hour volume >= USD 1,000,000 and rejects an indicated 45-minute gain above 80%. This is a separate ruleset, not equivalent to the Solana checks.

## Risk model
- Default risk budget: 1% of current virtual cash per trade.
- Maximum position: 10% of virtual cash.
- Maximum aggregate open exposure: 25% of virtual cash.
- Entry and exit simulation includes adverse slippage (0.30% per side) and fees (0.10% per side).
- Default stop-loss: 10% below simulated entry fill.
- Default take-profit: 20% above simulated entry fill.
- Both thresholds are checked against each fresh market quote (60-second refresh) and against manual paper marks; crossing either threshold closes the simulated position and records the exit reason in Supabase.
- Thresholds are configurable per signal. Simulated execution includes adverse slippage and fees; real fills are not guaranteed because this is paper trading.

## Current limitations
- No automatic 640-wallet tracker or wallet performance ranking.
- No automatic Solana token discovery / on-chain holder analytics yet.
- Candidate signals are manually entered in the UI in this first increment.
- Portfolio state is held in Streamlit session state and is not a durable, cross-device ledger.
- Major-asset prices and open-position marks refresh automatically from CoinMarketCap every 60 seconds; manual marks remain available for testing.
- No claim of AI-generated analysis or proven profitability; current agents are deterministic rule-based components.

## Validation gates before any live-trading discussion
1. Unit tests pass for thresholds, missing-data rejection, position sizing, costs, and P&L.
2. Historical/backtest and paper-trading logs include timestamps, source identifiers, fees, slippage, and rejected signals.
3. At least 30 days of forward simulation and a meaningful sample of trades are reviewed.
4. Results are measured net of fees/slippage and include max drawdown, expectancy, profit factor, win rate, and concentration.
5. Independent review of data quality, execution assumptions, and security.
6. A separate explicit user decision and separate security review would be required before any live execution feature is designed.

## Security
Never put API keys, passwords, wallet seed phrases, private keys, or .streamlit/secrets.toml in Git.
