# FinancialData.Net provider coverage audit

Audit date: 2026-11-01
Scope: public documentation review for the global multi-asset discovery engine.

## Documented coverage and plan gates

| Asset/data | Documented capability | Plan stated in docs |
|---|---|---|
| US stock symbols | Symbol directory | Free |
| International stock symbols | Directory for Toronto, London, Frankfurt, Euronext Paris/Amsterdam, Tokyo, Hong Kong, Singapore, Indonesia, Malaysia, Korea, Brazil, Mexico and India/Bombay | Free |
| US stock daily prices | More than 10 years of daily OHLCV | Free |
| International stock daily prices | More than 10 years of daily OHLCV | Standard |
| Real-time stock quotes | Quote, change and percentage change | Premium |
| ETF symbols | ETF directory | Free |
| ETF prices and quotes | Historical daily prices and real-time quotes | Premium |
| Commodity symbols and daily prices | Major commodity instruments; daily historical prices | Free |
| Index symbols and daily prices | Major indices; historical daily prices | Standard |
| Real-time index quotes | Major market indices | Premium |
| Futures symbols and daily prices | Futures across agricultural, energy, equity, FX, rates and metals | Standard |
| Crypto symbols and daily prices | Crypto pair directory and daily historical prices | Standard |
| Crypto minute history | One-minute historical bars | Standard |
| Real-time crypto quotes | Pair quotes | Premium |
| Forex symbols/prices/quotes | Directory, daily and minute history, real-time quotes | Premium |

Sources:
- https://www.financialdata.net/documentation
- https://www.financialdata.net/pricing

## Integration implications

1. The API documentation supports a broad multi-asset catalogue, but it does not establish that every configured seed ticker is covered. Resolve and validate each symbol against the provider's symbol directory before adding it to the canonical instrument catalogue.
2. A Free plan can bootstrap stock/ETF/commodity symbol discovery and daily prices for US stocks and commodities, but it is not sufficient for a global mixed-horizon live scanner.
3. Standard appears to be the minimum paid tier for historical/global coverage of international equities, indices, futures and crypto. Premium is required for the documented real-time quote families and forex data.
4. The published Free limit is 300 requests/day. Standard is 10 requests/second; Premium is 30 requests/second. Respect endpoint record limits (commonly 300) and offset pagination.
5. Documentation describes timestamps in different time zones by endpoint (for example UTC for crypto and EST for some equity/index quote endpoints). Normalize to timezone-aware UTC while retaining the original source timestamp and timezone metadata.
6. Do not infer futures continuous-contract behaviour, exchange mapping, quote-currency conversion, licensing rights or actual seed-symbol coverage from the marketing coverage list. Verify these with the account/API and provider terms.
7. Keep Binance/CoinMarketCap/Twelve Data adapters intact. FinancialData.Net should initially be an optional supplemental source, not a replacement.

## SDK integration gate

Before using the official Python SDK in a long-running worker, wrap or fix:
- finite request timeouts;
- bounded retries with exponential backoff and jitter;
- safe handling of connection failures before a response exists;
- bounded pagination and a shared rate limiter;
- normalized errors and source/provenance metadata.

## Decision

Do not purchase a plan yet. First perform a symbol-level coverage check for the actual seed universe and compare returned prices/timestamps with the existing providers. Then implement a read-only adapter behind a provider interface and test it with mocked responses. No live trading or automated order execution is in scope.
