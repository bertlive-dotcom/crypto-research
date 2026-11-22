# AI Research & Autonomous Systems — Crypto Research audit

**Audit date:** 2026-11-22  
**Repository:** `bertlive-dotcom/crypto-research`  
**Reviewed ref:** `main`  
**Reviewed commit:** `c89a4fd6476eb0bab91bc27c01185ac77317ac6c`

## Confirmed repository capabilities

- Streamlit dashboard with password gate and CoinMarketCap / Twelve Data market data.
- Existing paper-trading ledger and separate scanner persistence.
- Standalone Binance Spot scanner worker, configured for a five-minute cycle.
- Six-stage deterministic scanner pipeline: SCOUT, FILTER, ANALYST,
  RISK_MANAGER, EXECUTOR and LOGGER.
- Multi-asset research foundation with Binance crypto, FinancialData.Net,
  Alpha Vantage and EODHD adapters.
- Read-only assistant service and a private Telegram worker.
- Existing unit-test suites and scanner-specific staging target validation.

These six scanner stages are deterministic software roles, not independent
LLM agents. The AI Core must orchestrate existing domain capabilities rather
than duplicate their decision logic.

## Deployment observations

- GitHub default branch is `main`; latest observed commit is
  `c89a4fd` (2026-11-22).
- `render.yaml` defines a separate scanner worker and Telegram worker.
- Scanner deployment is pinned to the staging Supabase project ref
  `jgxrtvqxjtoxmdrpltng` through `SCANNER_ALLOWED_SUPABASE_PROJECT_REF`.
- `scanner.config.validate_staging_target` fails closed unless the configured
  Supabase URL exactly matches that allowlisted staging project.
- The current Streamlit app is not a separate AI Core dashboard; the new
  dashboard should be deployed independently.

## Supabase production observations

Project `crypto-research` (`bcwiihozbjworhkbufyf`) was active and healthy
at audit time. Public schema inspection found these tables:
`paper_trading_state`, `paper_trading_events`, `scanner_paper_state`,
`scanner_runs`, `market_candidates`, `trading_signals`,
`market_scanner_lock` and `market_alert_events`. RLS was enabled on all
eight inspected tables.

The migration-history API returned no recorded migrations. This is a schema
reproducibility and drift-management gap: the existing schema appears not to
have a tracked migration history in the inspected project. Do not apply new
AI Core DDL to production as part of this integration work.

The Supabase security advisor reported eight tables with RLS enabled but no
policies. A read-only grants inspection found no SELECT, INSERT, UPDATE or
DELETE grants for `anon` or `authenticated` on these tables; access is
currently service-role oriented. However, `market_alert_events` retained
non-DML grants (REFERENCES, TRIGGER and TRUNCATE) for anon/authenticated.
Review and revoke unnecessary privileges in a separately approved hardening
migration. No production changes were made during this audit.

The production schema SQL in the repository defines
`save_paper_trading_state` as SECURITY DEFINER and revokes execution from
PUBLIC, anon and authenticated, granting execution only to service_role.
Review all scanner RPC function grants and search_path settings before
reusing this pattern in the new platform.

## Staging inspection limitation

The staging project `crypto-research-staging`
(`jgxrtvqxjtoxmdrpltng`) was confirmed active and healthy. The database
metadata tools returned an ECONNRESET during table/migration inspection.
Therefore, staging schema parity has not yet been established. Retry read-only
inspection before applying any schema changes.

## Documentation drift

`AI_TRADING_DESK.md` still describes the six-stage pipeline as experimental
and branch-only, while the reviewed `main` version of
`scanner/worker.py` imports and executes `run_agent_pipeline`. Update the
documentation in a separate change after checking deployment history.

## Integration risks and required controls

1. Keep the existing scanner worker and paper ledger independent from the AI
   Core deployment.
2. Do not add new services to the existing Render production blueprint in this
   first increment.
3. The AI Core initially receives read-only research tasks only.
4. No direct access to service-role keys from the new dashboard or browser.
5. Use a dedicated central Supabase project/schema boundary; do not share
   production service-role credentials between services.
6. Keep AI Core schema changes out of production until a separate staging
   migration path is established and verified.
7. Add contract tests before enabling any network adapter.

## First implementation increment

Added a versioned task envelope and task result contract under
`integrations/ai_platform/`. This increment has no network calls, no database
access, no imports from the existing app/worker, and no deployment changes.
It is safe to review independently and is intended as the compatibility
boundary for the future central AI Core.
