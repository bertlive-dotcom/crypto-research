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
