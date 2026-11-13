# Telegram AI Trading Assistant

## Scope
A private Telegram worker reuses `assistant.service.ReadOnlyAssistantService`, the same read-only analysis service used by Streamlit. It is deployed as a separate Render Background Worker and does not import Streamlit. It does not access or mutate the paper ledger, Market Scanner state, exchange accounts or live orders.

Supported commands:
- `/start`, `/help`: help
- `/status`: configured provider status
- `/crypto [BTCUSD ETHUSD ...]`: 13 configured Binance Spot watchlist assets, daily and 4-hour analysis
- `/markets [NVDA SPY EURUSD]`: currently registered equity, ETF and FX instruments, daily analysis
- `/analyze SYMBOL`: exact allowlisted instrument
- `/report`: combined crypto and daily multi-asset report

“All markets” means every market group and instrument currently configured and supported by the existing assistant, not an unrestricted ticker universe. Indices, spot commodities and futures remain unavailable until exact symbols, adapters, timestamps, entitlements and licensing are validated. Gold spot must not be inferred from futures.

## Security
- `TELEGRAM_BOT_TOKEN` and provider credentials are Render environment secrets, never committed to Git.
- `TELEGRAM_ALLOWED_USER_ID` is the only permitted Telegram numeric user ID. Other users are ignored.
- Long polling uses Telegram HTTPS `getUpdates`; do not configure a webhook simultaneously.
- Messages use Telegram protected-content mode.
- No exchange API keys, order endpoints, wallet signing, withdrawals or portfolio mutation are included.
- The worker runs separately from the existing paper-scanner worker.

## Deployment
1. Create the bot with Telegram `@BotFather`.
2. Revoke any token exposed in screenshots or chats, then use only the newly issued token.
3. Start the private chat with the bot using `/start`.
4. In Render, create a Background Worker from this repository using the Telegram service in `render.yaml`.
5. Add `TELEGRAM_BOT_TOKEN`, `FINANCIALDATA_API_KEY`, `ALPHA_VANTAGE_API_KEY`, and `EODHD_API_TOKEN` to the worker's Environment panel. `TELEGRAM_ALLOWED_USER_ID` is prefilled from the user's confirmed ID; verify it before deploy.
6. Deploy and test `/status`, `/crypto`, `/markets`, `/analyze BTCUSD`, and `/report`.

Render worker environment and Streamlit secrets are separate; keep provider credentials synchronized manually. Never put the bot token in Streamlit source, GitHub, screenshots, or chat.

## Current limitations
This first iteration is command-driven and deterministic. It does not yet use an LLM for free-form conversation, persist chat preferences, or schedule proactive alerts. Add these only after the private command interface and provider quotas are validated. Provider entitlement and license restrictions remain as documented in `AI_TRADING_ASSISTANT_PROVIDER_AUDIT.md`.
