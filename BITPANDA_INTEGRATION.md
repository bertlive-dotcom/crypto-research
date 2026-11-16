# Bitpanda Portfolio Intelligence

## Scope
Read-only integration in the existing Streamlit dashboard. Refresh interval: 15 minutes. No trade, stake, unstake, transfer, deposit, or withdrawal operations are implemented.

## Credentials
Create a new Bitpanda Public API v2 key in Account Settings → API. Enable only:
- Balances (read)
- Transaction (read)
- Trade (read)
- Earn (read)

Do not enable Trade (Write), Earn (Write), or Transfer. Store the key only as `BITPANDA_API_KEY` in the Streamlit deployment secrets. The ChatGPT Bitpanda OAuth connector is separate from the dashboard API key and cannot be reused by the Streamlit process.

Also configure the existing server-side `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` secrets. Never add secrets to GitHub.

## Deployment
1. Review and merge this pull request.
2. Run `supabase/bitpanda_portfolio.sql` in the **production** Supabase SQL editor. Do not run it against staging unless explicitly testing there.
3. Add `BITPANDA_API_KEY` to Streamlit Community Cloud → App settings → Secrets.
4. Redeploy/restart the dashboard and open the Bitpanda Portfolio Intelligence page.
5. Verify holdings, recent operations and history against the Bitpanda web app.

## Data model
- `bitpanda_holdings_snapshots`: point-in-time holding values.
- `bitpanda_operations`: de-duplicated operation history keyed by Bitpanda operation ID.
- `bitpanda_portfolio_history`: provider portfolio history by timeframe.
- `bitpanda_earn_configs`: currently available Earn configurations, not active stakes.
- `bitpanda_sync_runs`: sync health and row counts.

All tables have RLS enabled and deny access to anon/authenticated roles. The server-side service role is the only integration writer/reader.

## Current limitations
- Cost basis and realized/unrealized P&L need a validated mapping of Bitpanda operation payloads; do not infer them from current holdings.
- Earn configuration APRs are product availability, not user staking balances.
- Card analytics are not included in this first dashboard increment; they can be added after the portfolio data model is validated.
- The integration stores the raw provider payload for auditability. Keep Supabase access restricted and apply a retention policy before broadening access.
