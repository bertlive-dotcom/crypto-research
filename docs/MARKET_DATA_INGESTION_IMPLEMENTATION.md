# Market Data Ingestion — Implementation Plan

**Status:** Phase 1 foundation started; staging validation blocked  
**Branch:** `feat/global-market-data-ingestion`  
**Target:** private, hybrid deployment; parallel provider migration  
**Production changes:** none

## Repository findings (2026-11-14)

- The main branch already contains read-only adapters for Binance Spot, FinancialData.Net, EODHD, Twelve Data and Alpha Vantage.
- The scanner is a separate five-minute worker and currently consumes Binance Spot directly. Its scoring, risk rules and paper ledger are out of scope for the first migration increment.
- Bigdata adapter work is in open PR #48 (`feat/bigdata-intelligence-connector`), not in main. Do not duplicate or silently merge that work into this branch.
- Multi-asset assistant architecture documentation is in open PR #49. Coordinate with it; this branch owns the data-ingestion implementation only.
- Supabase project IDs were verified against the project list: production is `bcwiihozbjworhkbufyf`; staging is `jgxrtvqxjtoxmdrpltng`.
- The earlier successful table inspection was against production (read-only): existing scanner/paper-trading tables and data are present, RLS is enabled, and the migration registry returned no recorded migrations. No production writes were made.
- Staging inspection currently fails with a database connection reset. No migration has been applied anywhere. Reconcile production schema history separately and inspect staging before applying DDL.

## Target architecture

1. Provider adapters fetch data server-side only.
2. A normalization/quality boundary validates identity, timestamps, OHLCV, currency and provenance.
3. A dedicated ingestion worker writes idempotently to private Supabase tables.
4. Streamlit and the Market Scanner read normalized snapshots through server-side application services.
5. Existing Binance scanner path remains authoritative until shadow validation passes.

## Canonical data contract

Every observation must retain:
- canonical instrument ID and canonical symbol;
- provider and provider-native symbol;
- asset class, exchange/venue and currency where known;
- interval and observation timestamps in UTC;
- original provider timestamp/timezone where supplied;
- OHLCV only when actually provided;
- source request/ingestion timestamp and quality status.

Never infer exchange aliases, fill missing volume with zero, relabel daily data as real-time, or silently substitute stale prices.

## Provider roles (initial)

| Provider | Initial role | Restrictions |
|---|---|---|
| Binance public Spot | Crypto Spot quotes/candles for supported pairs | Exchange-specific coverage; read-only |
| FinancialData.Net | Global symbol discovery, daily history and fundamentals where entitled | Quote real-time only with confirmed plan entitlement |
| EODHD | EOD and intraday feeds where the exact venue/plan supports them | Validate per-symbol coverage, timestamps and licence |
| Twelve Data | Secondary quotes/history where the plan supports the market | Validate WebSocket/REST quotas and venue entitlement |
| Alpha Vantage | Secondary historical/FX series | Not a default live quote feed |
| CoinGecko | Aggregated crypto price cross-check | Not the execution/scanner price source by default |
| Bigdata | Temporary comparison only, if account access permits | Existing work is in PR #48; no hard dependency |

## Phased implementation

### Phase 0 — branch and safety
- [x] Create isolated feature branch from current main.
- [x] Confirm Bigdata PR #48 and architecture PR #49 are separate open work.
- [ ] Inspect Streamlit/worker secret names and deployment configuration without exposing values.
- [ ] Restore/inspect staging and reconcile schema migration history.
- [x] Verify Supabase project IDs and distinguish production from staging.

### Phase 1 — normalization and adapters
- [ ] Add canonical instrument/provider-symbol registry implementation.
- [x] Define provider contract and structured capability/health models.
- [x] Add canonical candle normalization and quality tests.
- [ ] Implement provider-specific adapters against the contract.
- [ ] Validate symbol mapping, venue, currency, market session and quote-vs-trade semantics.
- [ ] Add per-provider quota/rate-limit accounting.

### Phase 2 — storage
- [x] Prepare additive SQL migration for private instrument, provider-symbol, quote, candle, fundamental, provider-run and quality-event tables.
- [x] Include RLS, client-role revokes and backend service-role grants in the migration.
- [x] Make `volume_available` a generated column derived from `volume`, preventing inconsistent inserts.
- [ ] Review SQL against the actual staging schema and apply to staging only after it is reachable.
- [ ] Add idempotent upserts and retention policies.

### Phase 3 — independent worker
- [ ] Add container, bounded scheduler, health checks and structured logs.
- [ ] Add separate ingestion cadence from the five-minute scanner.
- [ ] Persist provider health, request cost and data freshness.
- [ ] Keep all provider credentials in the deployment secret manager.

### Phase 4 — shadow validation
- [ ] Run old and new providers in parallel.
- [ ] Compare only equivalent instruments, venues, currencies, timestamps and price semantics.
- [ ] Require zero future candles, zero duplicate canonical keys and explicit stale-data handling.
- [ ] Preserve the scanner and paper-trading behavior unchanged.

### Phase 5 — controlled cutover
- [ ] Switch dashboard reads to normalized snapshots.
- [ ] Switch scanner reads only after a separate acceptance review.
- [ ] Keep a rollback switch to the prior read path.
- [ ] Retire Bigdata only after comparison and access/licence checks pass.

## Acceptance gates

- 100% correct mapping for enabled instruments; unresolved symbols stay disabled.
- No malformed OHLC, future timestamps, duplicate canonical candles or silent stale fallback.
- Quote freshness thresholds are defined per venue and asset class.
- Provider outage must fail closed for automated paper entries.
- Five consecutive market sessions of shadow operation with no critical data-quality incident.
- Existing scanner tests and paper-ledger regression tests pass unchanged.

## Security and operational constraints

- Never commit API keys, Supabase service-role keys, passwords or secret files.
- Never put service-role credentials in Streamlit browser/client code.
- Keep internal market-data tables inaccessible to anon/authenticated roles.
- No production schema changes, provider purchases, live orders or order API integration in this migration.
- Data display/redistribution rights must be verified for the exact account type and private-use deployment.

## Current blockers

1. Staging project (`jgxrtvqxjtoxmdrpltng`) is currently not inspectable due to connection resets; recheck before migrations.
2. Production project (`bcwiihozbjworhkbufyf`) has existing tables/data but an empty migration registry; reconcile before any production migration tooling.
3. The initial successful schema/RLS/grant inspection was read-only against production, not staging.
3. Real-time entitlements and permitted private display must be verified per provider, exchange and instrument.
4. Twelve Data, EODHD and FinancialData.Net adapters in main are not equivalent to a universal global real-time feed.


## Review update (2026-11-14)

- Rechecked PR #53: still open, draft and unmerged.
- Rechecked staging (`jgxrtvqxjtoxmdrpltng`): database inspection still fails with `ECONNRESET`; no DDL was executed.
- Static review found that the original `volume_available` default could disagree with a non-null `volume`. The SQL now derives this flag as a stored generated column, so it cannot drift from the actual volume value.
- The SQL remains unexecuted and unvalidated against a live staging schema. Provider adapter integration is held until source-specific timestamp/volume semantics and exact symbol coverage are handled safely.
- Existing EODHD, Twelve Data and FinancialData.Net adapters were reviewed. They expose narrower daily-history functionality and should not be presented as universal real-time feeds. Some daily candle timestamps need additional source-semantic validation before the canonical worker can consume them.
