# Market Data Ingestion — Implementation Plan

**Status:** Phase 0 started  
**Branch:** `feat/global-market-data-ingestion`  
**Target:** private, hybrid deployment; parallel provider migration  
**Production changes:** none

## Repository findings (2026-11-14)

- The main branch already contains read-only adapters for Binance Spot, FinancialData.Net, EODHD, Twelve Data and Alpha Vantage.
- The scanner is a separate five-minute worker and currently consumes Binance Spot directly. Its scoring, risk rules and paper ledger are out of scope for the first migration increment.
- Bigdata adapter work is in open PR #48 (`feat/bigdata-intelligence-connector`), not in main. Do not duplicate or silently merge that work into this branch.
- Multi-asset assistant architecture documentation is in open PR #49. Coordinate with it; this branch owns the data-ingestion implementation only.
- Production Supabase tables exist, but the migration registry returned no recorded migrations. Reconcile schema history before applying DDL.
- Staging project inspection returned a database recovery error. No staging migration or production write is permitted until staging is reachable and its schema is inspected.

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
- [ ] Inspect Streamlit/worker secrets and deployment configuration without exposing values.
- [ ] Restore/inspect staging and reconcile schema migration history.

### Phase 1 — normalization and adapters
- [ ] Add canonical instrument/provider-symbol registry.
- [ ] Implement provider contract and adapter-level tests.
- [ ] Validate symbol mapping, venue, currency, market session and quote-vs-trade semantics.
- [ ] Add per-provider quota/rate-limit accounting.

### Phase 2 — storage
- [ ] Prepare additive migration for private instrument, quote, candle, fundamental, provider-run and quality-event tables.
- [ ] Enable RLS and explicitly revoke client roles; grant only backend service role.
- [ ] Add idempotent upserts and retention policies.
- [ ] Apply to staging only after schema inspection.

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

1. Staging database was not inspectable during initial audit; recheck before migrations.
2. Production migration registry is empty despite existing tables; reconcile before migration tooling.
3. Real-time entitlements and permitted private display must be verified per provider, exchange and instrument.
4. Twelve Data, EODHD and FinancialData.Net adapters in main are not equivalent to a universal global real-time feed.
