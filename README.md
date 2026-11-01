# Crypto Research Dashboard

Streamlit MVP for a password-gated crypto and equities dashboard.

## Data sources
- CoinMarketCap API: BTC, ETH, SOL, LINK, XLM, SUI and HYPE.
- Twelve Data API: selectable stocks and ETFs (default AAPL, MSFT, NVDA, SPY, QQQ).
- Responses are cached for 60 seconds; the Refresh now button clears the cache.

## Deploy free with Streamlit Community Cloud
1. Open https://share.streamlit.io/ and sign in with the GitHub account that can access this repository.
2. Create an app from `bertlive-dotcom/crypto-research`, branch `main`, file `app.py`.
3. In the app settings, open **Secrets** and add the following TOML, replacing placeholders there (never in GitHub):

```toml
DASHBOARD_PASSWORD = "choose-a-long-unique-password"
CMC_API_KEY = "your-CoinMarketCap-key"
TWELVE_DATA_API_KEY = "your-Twelve-Data-key"
```

4. Deploy and test the password gate and both providers.

## Security
- This repository is public, so the source code is public. The dashboard asks for an app password; this is app-level protection, not infrastructure-level identity access control.
- Never commit API keys, passwords, or `.streamlit/secrets.toml`.
- Use a long unique password and share the app URL/password privately. For stronger access control, use a host with native authentication or make the repository private before deployment.
- The app only reads market data and cannot place trades.

## Limitations
- API fields, quotas and symbols depend on provider plan and coverage.
- Quote values are snapshots and timestamps/calculation methods can differ between providers.
- A source-comparison layer and stale-data warning rules remain to be added before decision-critical use.


## AI Crypto Trading Desk (simulation only)
The dashboard now includes a separate paper-trading tab with USD 80 virtual starting capital, a Solana-token ruleset, a major-asset volume ruleset, position sizing, fee/slippage assumptions, and simulated stop-loss handling.

The first increment is intentionally manual: token metrics and candidate signals are entered by the user. It does not track the 640 wallets mentioned in the reference post, discover Solana tokens automatically, or connect to wallets/exchanges. The five agent names represent deterministic software stages, not autonomous AI agents.

The paper ledger can be persisted in Supabase. Run `supabase/schema.sql` once in the Supabase SQL Editor, then add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to Streamlit Community Cloud Secrets. The service-role key must remain server-side and must never be committed to Git. Without these two secrets the app falls back to temporary session-only state; do not treat that as a durable 30-day journal. Major-asset positions can be marked from the CoinMarketCap snapshot when the app reruns; Solana token prices and on-chain metrics remain manual in this increment.

Run the local rule-engine tests with:

    python -m unittest discover -s tests -v

See [AI_TRADING_DESK.md](AI_TRADING_DESK.md) for rules, risk assumptions, limitations, and validation gates.


## Supabase paper-trading persistence
1. Create a Supabase project.
2. Open SQL Editor and run the complete script in `supabase/schema.sql`.
3. Copy the project URL and the **service_role** secret from Supabase project API settings.
4. In Streamlit Community Cloud, add these keys under App settings → Secrets:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR-SERVICE-ROLE-KEY"
```

The Streamlit server uses the service-role key for the database RPC and read-only history queries. It is not sent to browser JavaScript. Row-level security is enabled and direct access is revoked for anon/authenticated roles. Do not share this key or put it in GitHub. The paper ledger is a single-user MVP; do not expose the app password publicly. Back up the Supabase project before relying on the journal.


## Global multi-asset discovery foundation
See [GLOBAL_MARKET_ENGINE.md](GLOBAL_MARKET_ENGINE.md) for the selected global/mixed investment profile, supported asset-class configuration, provider-neutral scoring contract, safety boundaries and next integration steps. This foundation does not yet fetch global market data or connect FinancialData.Net.
