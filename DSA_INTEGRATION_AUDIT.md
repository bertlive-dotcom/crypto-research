# Daily Stock Analysis integration audit

**Status:** Phase 0 audit recorded; no DSA runtime code imported yet.  
**Target branch:** `feature/dsa-equity-integration`  
**Base:** `main`  
**Scope:** equities, ETFs and cryptocurrencies; research/read-only first, paper trading only after independent validation.

## Executive decision

Integrate selected capabilities behind the existing `crypto-research` services. Do **not** vendor the full Daily Stock Analysis application or add its complete dependency set to the Streamlit runtime.

The current repository already has a multi-provider market-data layer, normalized daily candle validation, technical indicators/scoring, an AI Trading Assistant and a separate crypto Market Scanner/paper ledger. The integration should extend these components instead of creating a second market-data or technical-analysis stack.

## Repository findings

### Existing `crypto-research` capabilities on main

- Streamlit dashboard in `app.py`.
- Provider adapters in `global_markets/providers/`: Binance, FinancialData.Net, EODHD, Twelve Data and Alpha Vantage.
- Shared market analysis and scoring in `global_markets/market_analysis.py` and `global_markets/scoring.py`.
- Cross-market context in `global_markets/cross_market.py`.
- Read-only multi-asset AI analysis in `assistant/`.
- A separate crypto scanner and paper-trading workflow; these must remain unchanged during the first integration.
- Existing tests and GitHub Actions cover core market data, assistant, scanner and trading-desk behavior.

### Existing equity work that must not be duplicated

Open draft PR **#35 — Add isolated equity research v1** already proposes a read-only eight-company technical screen (NVDA, TSM, ASML, MSFT, GOOGL, AMZN, AVGO and SU.PA) using FinancialData.Net and the existing candle/indicator stack. It is not merged into main and its CI/runtime validation was pending when audited.

This integration must review and coordinate with PR #35 rather than silently duplicating its dashboard tab or overlapping `app.py` changes. The longer-term equity service should generalize beyond that fixed universe and add fundamental/news evidence only where provider entitlement and data quality are verified.

Other open work relevant to coordination:
- PR #48: Bigdata.com intelligence connector foundation.
- PR #49: multi-asset AI Trading Assistant architecture.
- PR #53: market-data ingestion foundation.

No existing PR is being merged or modified by this audit branch.

## Daily Stock Analysis findings

- Upstream repository: `ZhuLinsen/daily_stock_analysis`, default branch `main`.
- Root project license: **MIT**.
- Screening subtree: `src/services/screening/` carries a separate **Apache License 2.0** notice.
- Upstream screening documentation states that its screening implementation is adapted from AlphaSift commit `9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf`, under Apache-2.0, with source headers and third-party notices retained.
- The screening module is integrated tightly with DSA's own strategy loading, provider manager, cache, storage, API and web UI. It is not a drop-in standalone package.
- Upstream has a broad application dependency set: data-source SDKs/crawlers, pandas/numpy, LiteLLM and model SDKs, search providers, SQLAlchemy, FastAPI, notification integrations and desktop/web support. Installing the entire `requirements.txt` into this repository would increase dependency and operational risk without being necessary for the selected capabilities.
- Upstream docs describe screening as a pipeline of market snapshot, hard filters, factor/risk scoring, bounded candidate context, optional LLM re-ranking and history persistence. Data-provider coverage and freshness are provider- and market-specific.

## Licensing and provenance requirements

1. Keep the upstream MIT license and copyright notice if MIT-licensed upstream files are copied or adapted.
2. If any code is copied or adapted from `src/services/screening/`, retain its Apache-2.0 license and required notices, include prominent change notices in modified files, and preserve applicable AlphaSift attribution/third-party notices.
3. Do not assume every DSA file is MIT solely because the repository root is MIT; respect subtree-specific notices and file headers.
4. Prefer clean-room adapters around documented behavior over copying large upstream modules.
5. Before shipping a copied module, inspect its complete file-level headers and all relevant third-party notices. This audit is not legal advice.

## Recommended integration boundary

```text
Streamlit dashboard (existing)
        |
        +-- existing crypto analysis / scanner (unchanged)
        |
        +-- equity research client
                |
                +-- isolated equity analysis service
                        |
                        +-- existing normalized market-data adapters
                        +-- fundamental-data adapter (entitlement-gated)
                        +-- news/catalyst evidence adapter (source + timestamp required)
                        +-- technical analysis reused from global_markets
                        +-- deterministic scoring and data-quality gates
```

The service boundary should expose versioned, typed request/response models and structured provider errors. It should not import the DSA WebUI, notification stack, portfolio implementation, database layer or complete API application.

## Selective feature plan

| Capability | Decision | Integration approach |
|---|---|---|
| Technical indicators | Reuse | Keep `global_markets.market_analysis` as the canonical implementation. Avoid duplicate RSI/MACD/SMA calculations. |
| Equity/ETF screening | Adapt | Generalize the existing market-data and instrument registry; do not hard-code the upstream China-market universe or provider assumptions. |
| Fundamentals | Selective | Add a provider-neutral contract; enable fields only when the connected data plan grants access and units/periods are validated. |
| News and catalysts | Selective | Normalize title, source, URL, publication time and retrieval time; unknown timestamps remain unknown. Treat article content as untrusted evidence. |
| AI agents / re-ranking | Reuse current assistant | Supply bounded, cited evidence to the existing assistant. LLM output must not bypass deterministic validation or risk gates. |
| Backtesting | Later phase | Reuse the existing validation discipline; require point-in-time data, costs, survivorship/look-ahead controls and untouched holdouts. |
| DSA WebUI, portfolio and notifications | Exclude | Existing dashboard, paper ledger and reporting workflows already own these responsibilities. |

## Unified analysis and safety rules

- Preserve asset class, instrument identity, exchange/venue, currency, provider, provider-native symbol, observation time, retrieval time, freshness and quality status.
- Do not silently substitute stale data, convert missing volume to zero, infer venue aliases or treat daily date buckets as verified exchange-session timestamps.
- A missing fundamental/news field is **unknown**, not a neutral or positive value.
- Keep technical, fundamental, catalyst, liquidity and risk components separately inspectable. Any aggregate score must publish coverage and algorithm version; insufficient coverage means no aggregate score.
- A score is a ranking aid, not a probability, forecast or order instruction.
- Keep crypto and equity paper ledgers separate. No live broker, wallet signing or order execution is in scope.
- No analysis result may create or mutate a paper position until a separate risk-gated paper-trading proposal has been explicitly implemented and tested.

## Delivery sequence

### Phase 0 — audit (this commit)
- [x] Inspect repository structure, current main SHA, branches and open PRs.
- [x] Inspect DSA repository tree, root license, screening license, requirements and screening documentation.
- [x] Identify overlapping equity work in PR #35 and related work in PRs #48, #49 and #53.
- [x] Create isolated feature branch from main.
- [ ] Complete file-level source/provenance review for any selected upstream modules.

### Phase 1 — contracts and isolated service
- Define instrument, analysis request, provider evidence, quality and response models.
- Implement service skeleton and health endpoint with no new provider dependency.
- Add adapter interfaces around existing normalized market data.
- Add unit tests with deterministic fixtures and provider-failure cases.

### Phase 2 — equity/ETF analysis
- Generalize universe selection and instrument mapping.
- Add entitlement-gated fundamental data.
- Add timestamped news/catalyst evidence.
- Produce transparent technical/fundamental/catalyst/risk components and coverage metadata.

### Phase 3 — unified intelligence
- Connect the equity service to the existing AI assistant through a bounded client.
- Add cross-asset ranking only when component coverage meets explicit thresholds.
- Keep existing crypto scanner and paper ledger untouched.

### Phase 4 — validation and production rollout
- Run CI and regression tests.
- Verify provider quotas, symbol coverage, data licenses and deployment secrets.
- Shadow-run against existing sources and compare only semantically equivalent data.
- Deploy the isolated service before enabling dashboard reads.
- Keep a feature flag and rollback path; no production schema migration until reviewed against the actual target environment.

## Current blockers / gates

- PR #35 needs a decision: merge/rebase and extend it, or keep this branch's service integration isolated and coordinate a later consolidation. Do not create a second Equity Research dashboard tab.
- FinancialData.Net, EODHD, Twelve Data, Alpha Vantage and any new fundamental/news provider require per-symbol entitlement, quota and redistribution-right checks.
- DSA's complete screening dependency graph and all file-level provenance still need review before copying any code.
- Production deployment and Supabase changes remain out of scope until the service contract and environment are verified.

## Audit baseline

- `crypto-research` main SHA at branch creation: `9d8092116c49a668323273f7c24fef47c4afba3f`.
- DSA main SHA inspected: `f044e95f2156d6c53cdeabf4bf27c60df4e366d5`.
- Branch: `feature/dsa-equity-integration`.
