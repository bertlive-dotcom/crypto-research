# FOMO Intelligence — implementation plan

**Status:** P0 design / integration discovery  
**Repository base:** `feature/midmarkets-scanner-visual-v1` (PR #43 head)  
**Requested configuration:** existing FOMO account · FOMO + on-chain sources · balanced trader profile · paper trading only.

## Non-negotiable safety boundary

- This module is research and simulation only.
- No live exchange order methods, wallet signing, transfers, withdrawals, private-key imports, or FOMO account automation.
- The module must fail closed unless `FOMO_EXECUTION_MODE=paper`.
- FOMO-derived observations are never sufficient by themselves to open a position.
- The existing Market Scanner hard gates, portfolio risk controls, daily-loss limits, duplicate-position checks, and paper ledger remain authoritative.
- Do not scrape authenticated FOMO pages, reverse-engineer private endpoints, automate the FOMO UI, or store FOMO login credentials.

## Important source distinction

FOMO Labs' first-party app does not publish a documented public developer API in the material reviewed for this plan. Third-party services advertise FOMO-family data APIs, but they are not official FOMO Labs services and must be treated as independent vendors. In particular, FomoAPI documents a metered API with API-key activation / staking requirements. Do not purchase, stake, or configure a third-party key until its operator, terms, data provenance, pricing, retention, and permission to use the data have been reviewed.

The on-chain leg is separate. Bitquery publishes a FOMO-specific Solana methodology: it attributes DFlow swap rows to the user's wallet through `Trade.Account.Owner`, while the transaction signer / fee payer is FOMO's shared app wallet. Bitquery reports a 94% match in a 1,166-trade sample, says the signer / fee-account addresses are inferred rather than confirmed by FOMO, and notes that its trade-level DEX coverage is roughly the latest 12 hours. The method does not map handles to wallets, does not cover FOMO's EVM orders, and may miss or misattribute routes outside the validated DFlow pattern. Therefore this is a candidate Solana feed, not complete FOMO coverage; validate signer activity and attribution continuously before accepting events. Other chains need separately validated providers and attribution rules. Never assume a public wallet address is a FOMO user merely because it trades the same token.

## Target architecture

```text
FOMO Intelligence (read-only)
  ├── FOMO social-data adapter (optional third-party provider; disabled until approved)
  ├── Public-wallet registry (addresses only; no private keys)
  ├── On-chain adapter (provider-neutral; Bitquery or another approved indexer)
  ├── Normalizer + schema validation + event deduplication
  ├── Trader performance evaluator (balanced profile)
  ├── Social / on-chain confluence engine
  ├── Token safety and market-liquidity gates
  └── Signal observations + audit trail
             |
             v
Existing Market Scanner (technical gates remain authoritative)
             |
             v
Existing six-stage agent pipeline / portfolio risk manager
             |
             v
Existing paper_entry / paper_exit and Supabase paper ledger
```

FOMO Intelligence must initially run as an independent observer. It must not mutate scanner candidates or call `paper_entry` directly in P1/P2.

## Configuration contract

Initial defaults (safe/off until source approval):

| Variable | Initial value | Purpose |
|---|---|---|
| `FOMO_INTELLIGENCE_ENABLED` | `false` | Master kill switch |
| `FOMO_SOURCE_MODE` | `both` | FOMO + on-chain |
| `FOMO_TRADER_PROFILE` | `balanced` | Balanced trader scoring |
| `FOMO_EXECUTION_MODE` | `paper` | Only permitted execution mode |
| `FOMO_API_BASE_URL` | unset | Explicitly approved third-party endpoint only |
| `FOMO_API_KEY` | unset | Hosting secret; never committed or displayed |
| `ONCHAIN_PROVIDER` | unset | Approved chain indexer |
| `ONCHAIN_API_KEY` | unset | Hosting secret; never committed or displayed |
| `FOMO_MAX_EVENT_AGE_SECONDS` | `900` | Reject stale social events |
| `FOMO_CONFLUENCE_WINDOW_SECONDS` | `900` | 15-minute clustering window |
| `FOMO_MIN_QUALIFIED_TRADERS` | `3` | Minimum independent traders for cluster signal |

The account selection `existing` is an operator-side fact only. It does not imply API access or grant permission to automate the FOMO app.

## Canonical normalized records

### Trader snapshot
- `provider`, `provider_trader_id`, `handle`
- `wallets`: public Solana / EVM addresses, nullable
- `observed_at`, `source_updated_at`
- `realized_pnl_usd`, `unrealized_pnl_usd` (nullable and kept distinct)
- `closed_trade_count`, `win_rate`, `profit_factor`, `max_drawdown_pct`
- `history_days`, `data_completeness`, `privacy_status`

### Trade observation
- `event_id` (stable deduplication key), `provider`, `chain_id`
- `trader_id`, `wallet_address`, `token_address`, `symbol`
- `side`, `usd_value`, `token_quantity`, `price_usd`
- `transaction_hash`, `block_time`, `observed_at`
- `confidence`, `attribution_method`, `is_confirmed`

Unknown values stay null. Never coerce missing PnL, prices, timestamps, or volumes to zero.

## Balanced trader score — first calibration hypothesis

Use only comparable, sufficiently complete history. A proposed initial score is:
- realized net profitability: 20%
- maximum drawdown / downside control: 20%
- consistency across rolling periods: 15%
- profit factor: 15%
- win rate: 10%
- closed-trade sample size and history length: 10%
- data completeness / attribution confidence: 10%

Do not rank from 24h PnL alone. Separate realized from unrealized returns; account for fees where the source provides them. Require a minimum closed-trade sample and history window before a trader can qualify. The score and minimum sample are hypotheses to calibrate, not claims about predictive performance.

## Social / on-chain signal rules

- Deduplicate by transaction hash + chain + log / swap index where available; otherwise use provider event ID and retain the source key.
- Count unique trader identities, not repeated wallet events from the same person.
- Cluster only confirmed buys in the configured 15-minute window; buys and sells remain separate observations.
- Require at least 3 independently qualified traders for a multi-trader-buy observation.
- Label signals as `OBSERVATION`, `WATCH`, `CONFIRMED_BY_MARKET`, or `REJECTED`; never label an unvalidated cluster as a buy order.
- Apply token contract / mint validation, liquidity, volume, spread / slippage, token age, concentration, and market-data freshness checks.
- If FOMO and on-chain sources disagree, data is stale, or attribution confidence is low, downgrade or reject the signal.
- The existing Market Scanner must independently confirm technical conditions before a paper candidate can proceed.

## Phased delivery and acceptance criteria

### P0 — source and permission validation (current)
1. Confirm the FOMO account can expose the public wallet addresses for the user's own account / selected public traders.
2. Evaluate the third-party FOMO-data provider separately from FOMO Labs; verify terms, data provenance, credit pricing, rate limits, retention, and whether automated internal analysis is permitted.
3. Validate Bitquery's documented Solana DFlow attribution against a fresh sample: check the shared signer is still active, compare user wallet ownership, and measure false positives / missed routes; explicitly record the ~12-hour DEX trade-history limit and the lack of handle-to-wallet mapping.
4. Decide whether to use Bitquery for Solana only, then separately assess EVM coverage; confirm provider cost, latency, pagination, websocket / polling behavior, and historical coverage.
5. Do not enable ingestion until these checks pass.

**Acceptance:** written source decision, documented provider limitations, and a reproducible sample of correctly attributed transactions. No credentials or live trading.

### P1 — read-only data foundation
- Add isolated `fomo_intelligence/` package with typed normalized records, provider interfaces, config validation, event deduplication, and provenance metadata.
- Add read-only provider clients only after P0 approval.
- Store observations in dedicated tables, separate from the existing paper portfolio and scanner tables.
- Add tests for malformed payloads, null fields, duplicate events, stale data, pagination, rate limits, and provider outages.

**Acceptance:** deterministic fixtures pass; no calls to order / wallet-signing endpoints; feature remains off by default.

### P2 — trader evaluation and confluence
- Implement balanced trader scoring using closed-trade history and explicit missing-data handling.
- Build 15-minute multi-trader buy/sell clusters with unique trader counts and confidence.
- Add token risk gates and a full decision audit trail.

**Acceptance:** backtest / replay against timestamped observations; no look-ahead bias; every signal is explainable and traceable to source records.

### P3 — dashboard
- Add an interactive FOMO Intelligence section to Streamlit using MIDMarkets visual conventions.
- Use interactive Plotly charts and expandable trader / token detail cards; do not introduce static dataframe tables.
- Show provider health, last successful sync, stale-data warnings, source attribution, confidence, trader score components, and cluster timeline.
- Keep FOMO Intelligence visually and logically separate from real Bitunix account data and existing paper balances.

**Acceptance:** desktop and iPhone review; unavailable data is visibly unavailable, never fabricated.

### P4 — paper-only scanner integration
- Pass FOMO observations as optional context to the existing six-stage pipeline.
- Social data may add context or confidence, but cannot override technical hard gates or portfolio risk controls.
- Use a separate signal namespace and idempotency key so FOMO events cannot duplicate existing scanner entries.
- Route any approved candidate only through the existing paper execution path.
- Explicitly reject any execution mode other than `paper`.

**Acceptance:** tests prove no live order path exists; an end-to-end staging cycle creates only paper events.

### P5 — evaluation before any future scope change
- Collect at least 100 paper observations / simulated trades across market regimes.
- Report net results after fees and conservative slippage, win rate, profit factor, max drawdown, false-positive rate, signal latency, and source attribution failures.
- Compare technical-only scanner results with technical + FOMO context using out-of-sample periods.
- Do not change execution scope as part of this project; any future request for real-money execution requires a separate design and explicit review.

## Repository integration notes

- Current working baseline is PR #43 head, which contains the MIDMarkets interactive chart / card redesign and is still an open draft PR. Build FOMO work on a separate branch from that head; do not modify or merge PR #43.
- Existing scanner worker runs on a five-minute interval, uses Binance public Spot data, a Supabase-backed scanner store, a six-stage deterministic paper pipeline, and a fail-closed staging-project guard.
- Existing scanner risk rules and paper ledger are authoritative. The FOMO package must not change their thresholds or database state in P1/P2.
- The existing app already has manual Solana metrics in the paper desk; this is not an automated on-chain feed and must not be represented as one.
- Keep API keys in Render / Streamlit Secrets. Never add keys, wallet seed phrases, private keys, or FOMO passwords to Git.

## Current implementation status

This document records the agreed configuration and technical plan. It does **not** claim that FOMO or on-chain feeds are connected, that provider access has been approved, or that any signals / paper trades are running.
