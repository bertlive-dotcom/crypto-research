# CORE-041 read-only data contract

## Endpoint

`GET /internal/v1/strategy-validation/dataset?symbol=BTCUSDT&limit=500`

- Requires `Authorization: Bearer <CRYPTO_RESEARCH_INTERNAL_API_TOKEN>`.
- Reads the scanner's dedicated `scanner_paper_state` and latest candidate snapshot.
- Uses the service-role credential only on the server; it is never returned to callers.
- Supports an optional canonical USDT spot pair filter.
- `limit` is bounded to 1–2000 closed trades; candidate output is capped at 500.
- Returns `schema_version=1.0`, `read_only=true`, and `mode=simulation_only`.
- Does not expose scanner writes, ledger mutation, exchange credentials, or order execution.

## Trade normalization

Each closed paper trade is returned with:
- `gross_pnl`: P&L calculated from reference entry/exit prices and quantity, before simulated costs.
- `net_pnl`: persisted `realized_pnl_usd`, after simulated fees and slippage.
- `total_cost`: `gross_pnl - net_pnl`, only when source values are complete and consistent.
- `quote_currency=USDT`, timezone-aware `closed_at`, and `cost_status`.

Missing or inconsistent values are returned as `null` with explicit `data_quality_issues`. They are never coerced to zero. CORE-041 must treat any trade with unknown `total_cost` as incomplete cost coverage and block eligibility.

## Run and configuration

Install `requirements-api.txt`, configure:
- `CRYPTO_RESEARCH_INTERNAL_API_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Keep the service on a private network or enforce service-to-service authentication at the network boundary. Never put either secret in a client app, source control, or logs.

## Limitations

- Only closed Market Scanner paper trades are included.
- Candidate rows are the latest persisted scanner snapshot.
- Costs are reconstructed from the scanner's reference-price P&L and persisted net P&L; this is valid only for records containing the required reference prices, quantity, and realized P&L.
- This contract does not claim statistical robustness, out-of-sample validity, or profitability.
- No live-trading capability is provided.
