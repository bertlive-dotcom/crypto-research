# AI Trading Assistant — multi-asset architecture and implementation plan

**Status:** Architecture proposal; documentation only  
**Target markets:** Crypto, equities, ETFs and gold (XAUUSD)  
**Interfaces:** Streamlit dashboard + Telegram  
**Initial operating mode:** Research and paper trading only  
**Live execution:** Out of scope; requires a separate approval, security review and implementation decision

## 1. Executive decision

Extend the existing research and paper-trading platform rather than create a second trading engine.

Reuse:
- `trading_desk.py` as the authoritative deterministic paper-position, sizing, cost, stop-loss, take-profit and P&L engine.
- The standalone Binance Market Scanner and its isolated paper portfolio.
- `global_markets/` for provider-neutral multi-asset discovery, normalized market data and technical screening.
- Existing Twelve Data, FinancialData.Net, Alpha Vantage and Binance adapters where their instrument coverage and account entitlements are verified.
- Supabase for durable records and Streamlit for the existing authenticated dashboard.

Add a thin assistant orchestration layer, a Telegram transport, a shared alert/event service and a normalized instrument registry. The language model is an explanation and workflow layer only: it must never bypass deterministic eligibility, sizing or risk controls.

## 2. Target architecture

```text
                 ┌──────────────────────────────┐
                 │       User / Access          │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────┴───────────────┐
                 │                              │
        ┌────────▼────────┐            ┌────────▼────────┐
        │ Streamlit UI    │            │ Telegram Bot    │
        │ dashboard/chat │            │ commands/alerts │
        └────────┬────────┘            └────────┬────────┘
                 │                              │
                 └──────────────┬───────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Assistant API /       │
                    │ Application services  │
                    └───────────┬───────────┘
                                │
          ┌─────────────────────┼──────────────────────┐
          │                     │                      │
 ┌────────▼────────┐  ┌─────────▼────────┐  ┌──────────▼─────────┐
 │ Context &       │  │ Deterministic    │  │ Alert &            │
 │ conversation   │  │ analysis/risk    │  │ notification       │
 │ orchestration  │  │ services         │  │ service            │
 └────────┬────────┘  └─────────┬────────┘  └──────────┬─────────┘
          │                     │                      │
          └─────────────────────┼──────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Existing domain layer│
                    │ scanner / market      │
                    │ analysis / paper desk │
                    └───────────┬───────────┘
                                │
          ┌─────────────────────┼──────────────────────────┐
          │                     │                          │
 ┌────────▼────────┐  ┌─────────▼────────┐       ┌─────────▼────────┐
 │ Binance         │  │ Twelve Data /    │       │ FinancialData.Net│
 │ crypto data     │  │ Alpha Vantage    │       │ equities, ETFs,  │
 │                 │  │ equities / FX    │       │ commodity history│
 └─────────────────┘  └──────────────────┘       └──────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Supabase              │
                    │ assistant, alerts,    │
                    │ audit and paper data  │
                    └───────────────────────┘
```

### Deployment boundary

- Keep the existing Streamlit app and Binance scanner worker independently deployable.
- Add an assistant API/web service and a Telegram webhook/polling process as a separate Render service. Both transports call the same application services; neither contains trading rules.
- Prefer a webhook for production Telegram delivery. Polling is acceptable for local development only. Do not run multiple polling replicas.
- The Telegram bot token and provider credentials live only in Render/Streamlit server-side secrets.
- The assistant service must not write to the scanner's isolated portfolio tables or the dashboard's singleton paper state except through the existing domain/persistence interfaces.

## 3. Asset and instrument model

All instruments use a provider-neutral identity; provider symbols are aliases, not primary keys.

Minimum fields:
- `instrument_id` (stable internal ID), `asset_class`, `canonical_symbol`, `display_name`
- `venue`, `quote_currency`, `provider`, `provider_symbol`
- `timezone`, `trading_calendar`, `session_type`
- `price_precision`, `quantity_precision`, `contract_multiplier`
- `is_active`, `coverage_status`, `last_verified_at`

Initial universe:
- **Crypto:** preserve the existing configured watchlist and Binance pair-eligibility checks. Do not assume every configured asset has a currently tradable Binance Spot pair.
- **Equities and ETFs:** reuse the existing equity research universe and Twelve Data / FinancialData.Net coverage checks.
- **Gold:** introduce canonical `XAUUSD` as a research instrument. Before enabling alerts or paper fills, verify a source that supplies timestamped OHLC/quotes, market hours, spread or a defensible cost proxy, and the exact instrument convention. Spot gold is OTC; provider symbols and CFD contracts are not interchangeable.
- Indices, futures and unsupported symbols remain explicitly unavailable until a source and contract specification are verified.

Each data point carries source, provider symbol, observed timestamp, candle open/close timestamps, interval, currency and quality flags. Never silently substitute symbols or mix adjusted and unadjusted equity prices.

## 4. Application modules

Proposed package boundaries (adapt names to the current repository conventions after code review):

| Module | Responsibility |
|---|---|
| `assistant/instruments.py` | Instrument registry, canonical IDs and provider mappings |
| `assistant/market_data.py` | Provider-neutral quote/candle contract, freshness and quality checks |
| `assistant/context.py` | Conversation context and compact evidence bundles |
| `assistant/analysis.py` | Calls existing technical, cross-market and scoring functions |
| `assistant/trade_review.py` | Pre-trade checklist and explainable setup summary |
| `assistant/performance.py` | Six-month trade review, attribution and risk metrics |
| `assistant/risk_gate.py` | Deterministic eligibility and paper-order authorization |
| `assistant/alerts.py` | Event normalization, deduplication, preferences and delivery |
| `assistant/orchestrator.py` | Use-case coordination; no direct broker/exchange access |
| `api/` | Authenticated HTTP endpoints and Telegram webhook |
| `telegram_bot/` | Telegram command parsing, identity allowlist and message formatting |

The LLM may summarize verified evidence, explain rule outcomes and ask clarifying questions. It must not invent prices, probabilities, fills, news, fundamentals or source timestamps. If evidence is missing or stale, it must say so and return an unavailable/insufficient result.

## 5. Core workflows

### A. Before-opening trade review
1. Resolve the requested symbol to one canonical instrument; ask for venue/contract if ambiguous.
2. Fetch synchronized, sufficiently fresh closed candles and current quote where available.
3. Run asset-class-specific analysis; do not apply crypto liquidity or 24/7 assumptions to equities or gold.
4. Build a proposed setup: direction, entry type/zone, invalidation, stop, target(s), holding horizon and evidence.
5. Calculate position size from the existing risk engine, including contract multiplier, quote currency, fees, spread/slippage and FX conversion where required.
6. Run the deterministic risk gate. Failed or unknown checks reject the proposal; the LLM cannot override them.
7. Return a structured proposal with source timestamps, assumptions, missing fields and a clear paper-only status.
8. Require explicit confirmation before creating a paper order. No live order path exists.

### B. Six-month performance review
- Read closed and open trades from the correct portfolio/ledger; do not combine scanner and dashboard portfolios without an explicit portfolio selector.
- Normalize realized and unrealized P&L to a selected base currency using timestamped FX rates.
- Include fees, slippage and funding/borrow costs where available; mark missing costs rather than assuming zero.
- Report total and annualized return where meaningful, max drawdown, expectancy, profit factor, win rate, average win/loss, exposure, holding time, asset-class and strategy attribution, and rejected/invalidated setups.
- Distinguish realized, unrealized and mark-to-market P&L. Explain sample-size limitations and avoid claiming predictive causality.

### C. Unusual-market activity
- Generate events from deterministic thresholds on closed candles and verified quote/volume data.
- Use separate thresholds and session-aware baselines for crypto, equities/ETFs and XAUUSD.
- Event types include volatility expansion, volume anomaly, gap/session open, trend/relative-strength change and source/data-quality degradation.
- Alerts are informational, deduplicated and rate-limited. An alert is not an entry instruction.

## 6. Risk, authorization and safety invariants

1. **Paper-only:** no exchange order endpoints, broker trading APIs, wallet signing, private keys or withdrawals.
2. **One risk authority:** reuse the current deterministic trading engine; no duplicated sizing or exit implementation.
3. **Fail closed:** missing, stale, unsynchronized or ambiguous market data cannot authorize a paper entry.
4. **Portfolio isolation:** keep existing dashboard and scanner ledgers independent. Introduce a portfolio registry before any cross-portfolio reporting.
5. **Instrument-aware sizing:** crypto units, equity shares and XAUUSD contract/lot sizes are different. Require verified contract metadata before calculating quantity.
6. **Risk budgets:** preserve current $80 scanner portfolio and its current controls. Any new assistant portfolio has a separate explicit virtual starting balance and configured limits; never silently share cash or exposure.
7. **Human confirmation:** paper order creation requires an explicit user confirmation. Telegram messages must not trigger orders merely because they contain natural-language intent.
8. **Telegram access:** allowlist numeric Telegram user IDs; reject all other senders. Verify webhook secret token, rate-limit commands, and do not expose sensitive account data in group chats.
9. **Secrets:** server-side environment variables only. Never place Supabase service-role keys, Telegram tokens, provider keys or credentials in browser code, logs, Git or Telegram messages.
10. **Auditability:** persist request, evidence references, rule versions, risk decision, user confirmation, resulting paper event and delivery status.
11. **LLM isolation:** treat user messages, provider text and retrieved content as untrusted data. Tool permissions are explicit and read-only by default.
12. **No performance claims:** an LLM explanation or backtest does not establish a tradable edge.

## 7. Telegram interface

Initial read-only commands:
- `/start` — private onboarding and access check.
- `/help` — command reference.
- `/status` — data freshness, scanner status and paper portfolio summary.
- `/scan crypto|stocks|etfs|gold` — latest qualified candidates.
- `/analyze SYMBOL` — evidence-backed instrument analysis.
- `/review 6m` — performance report for the selected paper portfolio.
- `/alerts on|off` — notification preference.
- `/watch SYMBOL` — add an instrument to the user's watchlist.

Paper proposal flow (later phase):
- `/review-trade SYMBOL` creates a proposal only.
- Bot returns a structured summary and unique proposal ID.
- User confirms with an explicit inline confirmation action in the private chat.
- Confirmation revalidates quote freshness, proposal expiry, risk limits and duplicate-order idempotency before paper execution.
- Expired or changed proposals require a new review. No natural-language-only confirmation.

## 8. Dashboard experience

Add an **AI Assistant** area to Streamlit with:
- Chat and suggested workflows.
- Asset-class selector and canonical instrument search.
- Evidence panel: price/candle timestamps, source, freshness and quality.
- Trade proposal card: direction, entry, stop, target, size, risk amount, R multiple and rejection reasons.
- Six-month performance review with equity curve, drawdown and asset/strategy attribution.
- Alert feed and per-instrument preferences.
- Audit detail view and clear paper-only labels.

The dashboard remains the primary rich interface; Telegram is a compact command, alert and approval surface. Both call the same backend services and share durable state.

## 9. Persistence design (proposed; no migration in this architecture PR)

Create a later, reviewed migration after mapping the existing Supabase schema and RLS model.

Candidate tables:
- `assistant_conversations`: owner, interface, created/updated timestamps and status.
- `assistant_messages`: conversation, role, content, structured payload, model/provider metadata and timestamp.
- `instrument_registry`: canonical instrument identity and provider mappings.
- `assistant_watchlists`: owner, instrument and alert preferences.
- `assistant_alert_events`: dedupe key, instrument, event type, evidence, severity and source timestamps.
- `assistant_alert_deliveries`: event, channel, destination reference, status, retries and delivered timestamp.
- `trade_proposals`: portfolio, instrument, direction, levels, quantity, risk, evidence snapshot, ruleset version, expiry and status.
- `assistant_audit_events`: actor, action, input/output references, authorization decision and correlation ID.

Do not duplicate the authoritative paper trade ledger. Link proposals and audit events to existing paper-trading/scanner records using stable identifiers. Define ownership and access policies before exposing any table. Service-role access remains server-side only; enable RLS on exposed tables and test policies for every operation.

## 10. API contracts (initial proposal)

- `GET /health` — liveness only; no secrets or account data.
- `POST /assistant/message` — authenticated conversation request; returns text plus structured evidence references.
- `GET /instruments/search?q=` — canonical instrument resolution.
- `POST /analysis/instrument` — read-only multi-asset analysis.
- `POST /analysis/trade-review` — creates a non-executable paper proposal.
- `GET /performance/review?portfolio_id=&period=6m` — ledger-backed review.
- `GET /alerts` and `POST /alerts/preferences` — event feed and preferences.
- `POST /telegram/webhook` — validates Telegram webhook secret and sender allowlist before dispatch.

All mutating endpoints require authenticated identity, idempotency keys and audit records. The API must not expose a generic execute-order endpoint.

## 11. Implementation plan and acceptance gates

### Phase 0 — repository and provider audit
- Map current modules, tests, Supabase tables/RLS, Render services and open PR changes.
- Verify actual provider coverage and entitlements for the selected equity/ETF universe and XAUUSD.
- Choose the Telegram library and LLM provider only after dependency, hosting and data-retention review.
- Record canonical instrument IDs and data-quality rules.
**Exit:** no duplicate engine or portfolio; provider coverage matrix with verified, unavailable and pending symbols.

### Phase 1 — shared assistant domain and API skeleton
- Add instrument registry contracts and normalized quote/candle models.
- Add freshness, timezone, session and provider-quality validation.
- Add authenticated API skeleton, request correlation IDs and structured logging.
- Add deterministic service adapters to existing analysis and risk modules.
**Exit:** unit tests for instrument resolution, stale data rejection, closed-candle handling, currency and contract metadata.

### Phase 2 — dashboard assistant (read-only)
- Add chat/workflow UI and evidence panel.
- Implement `/analyze`, pre-trade review and six-month performance report as read-only workflows.
- Use only verified provider fields; clearly label unavailable data.
**Exit:** reproducible answers from stored evidence; no write to any paper portfolio.

### Phase 3 — Telegram read-only interface
- Add webhook, sender allowlist, webhook secret validation and command routing.
- Implement status, scan, analyze, review and alert preferences.
- Add delivery retries, rate limits and deduplication.
**Exit:** unauthorized sender tests, replay tests, duplicate update tests and no secrets in logs.

### Phase 4 — alerting and gold coverage
- Add asset-class-aware unusual-activity rules and subscriptions.
- Verify XAUUSD source, instrument convention, trading hours, timestamps, precision and costs.
- Add XAUUSD only after the coverage checklist passes.
**Exit:** alert replay/deduplication tests, stale-feed suppression and verified gold data fixture/live smoke test.

### Phase 5 — paper proposals and confirmation
- Create proposal records with expiry and full evidence snapshots.
- Add explicit dashboard and private Telegram confirmation.
- Revalidate price, quote age, duplicate signal, sizing, exposure and daily-loss controls at confirmation time.
- Route only through existing paper-trading domain methods.
**Exit:** end-to-end tests prove there is no live execution path and all rejected/expired proposals are audited.

### Phase 6 — forward validation and review
- Run at least 30 days of forward paper simulation with a meaningful trade sample.
- Compare assistant proposals with baseline scanner and no-trade benchmark.
- Report net-of-cost expectancy, max drawdown, profit factor, win rate, turnover, slippage sensitivity and performance by asset class.
- Conduct independent data-quality, security and operational review.
**Exit:** documented validation report and separate explicit decision before any discussion of live trading.

## 12. Test strategy

- Unit: symbol mapping, sessions, timezone conversion, candle closure, freshness, missing data, precision, contract multipliers, FX conversion and risk calculations.
- Integration: each provider adapter with recorded fixtures and controlled live smoke tests.
- Regression: existing `trading_desk.py`, scanner, global-market and paper-ledger suites must remain unchanged and pass.
- Security: Telegram sender spoofing, webhook secret failure, replay/idempotency, authorization, RLS, secret scanning and log redaction.
- Workflow: read-only analysis, expired proposal, stale quote at confirmation, duplicate proposal, daily loss limit and portfolio isolation.
- Operational: worker restart, webhook retry, provider outage, rate-limit handling and Supabase unavailable mode.

## 13. Immediate next engineering tasks

1. Audit the current `main` tree and active PRs before touching shared files.
2. Build a provider coverage matrix for all target instruments, especially XAUUSD.
3. Implement the instrument/data contracts and read-only assistant API on a feature branch.
4. Add dashboard read-only assistant before Telegram write/confirmation flows.
5. Add Telegram read-only commands and alerts after identity/security controls are tested.
6. Add paper proposal confirmation only after the prior phases pass.

## 14. Explicit non-goals

- No €450-style broker deposit or third-party account requirement.
- No broker custody, deposits, withdrawals or wallet connection.
- No live order placement or exchange private API keys.
- No claim that the assistant predicts prices or guarantees profitability.
- No merging of the existing independent paper portfolios.
- No enabling XAUUSD execution until contract and cost conventions are verified.
