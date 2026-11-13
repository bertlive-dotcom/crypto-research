# AI Trading Assistant — provider coverage audit

**Audit date:** 2026-11-13  
**Scope:** Existing `main` branch code and repository documentation. No live API credentials were used for this audit.

## Executive result

The repository has reusable adapters for crypto Spot candles, FX daily history, and daily equity/ETF/commodity history. That is not equivalent to verified real-time coverage: provider plan entitlements, per-symbol history access, quote freshness and licensing still need runtime checks.

**XAUUSD spot is not currently covered by an explicit provider mapping or quote adapter in the repository.** Do not enable gold analysis or paper sizing from the existing `GC` futures symbol. Gold Spot (XAUUSD), COMEX gold futures (GC) and a broker CFD are different instruments and have different sessions, multipliers, costs and price conventions.

## Coverage matrix

| Asset class / instrument | Existing repository support | Current status | Gate before use |
|---|---|---|---|
| Crypto Spot (mapped Binance pairs) | Binance public exchange-info + OHLCV adapter; closed-candle analysis | Adapter implemented; live symbol availability is checked at request time | Verify current pair listing, freshness, source and quote currency |
| Equities | Twelve Data quote path in dashboard; FinancialData.Net daily history | Adapter paths implemented; account entitlements are not proven by symbol-directory matches | Verify quote/history access, venue, currency, adjustment and timestamps per symbol |
| ETFs | Twelve Data quote path; FinancialData.Net daily history | Adapter paths implemented; per-symbol plan coverage unverified | Verify each instrument and source limits |
| FX | Alpha Vantage daily FX history; FinancialData.Net has FX quote/history endpoint definitions | Daily adapter implemented; intraday entitlement and live quote coverage unverified | Verify authorized plan, timestamp semantics, spread and request quota |
| Commodity futures (e.g. GC) | FinancialData.Net commodity directory and daily OHLCV endpoint | Daily-history adapter implemented; entitlement and contract details unverified | Verify exact contract, roll policy, multiplier, currency and history access |
| Gold Spot XAUUSD | No explicit provider symbol mapping, spot quote feed or intraday adapter in current assistant-ready code | **Pending / unsupported** | Select a licensed spot data source and verify quote/candle endpoints, timestamp, session, bid/ask, spread, precision and source symbol |

## Evidence in the codebase

- `global_markets/providers/binance.py`: public Spot exchange-info and OHLCV klines; no account/order endpoints.
- `global_markets/crypto_feed.py`: explicit canonical-to-Binance pair mappings and runtime listing checks.
- `global_markets/providers/alphavantage.py`: daily FX and crypto history; no XAUUSD spot endpoint.
- `global_markets/providers/financialdata.py`: symbol directories and daily price adapters for equities, ETFs, commodities, futures, crypto and FX; quote normalization has asset-class timestamp constraints.
- `GLOBAL_MARKET_ENGINE.md`: FinancialData.Net daily commodity history is optional and plan-dependent; it is not a real-time quote guarantee. Index/futures coverage remains subject to verification.

## Important limitations

1. A symbol appearing in a directory does not prove historical endpoint entitlement.
2. A daily bar cannot be treated as a real-time quote or intraday alert source.
3. A futures ticker such as GC must not be relabelled XAUUSD.
4. Missing volume, spread, contract multiplier or timestamp must remain unavailable, not be imputed.
5. No live provider smoke test was performed because no API credentials were accessed in this audit.

## Recommended provider decision for gold

Keep `COMMODITY:XAU:USD` registered as `pending_verification`, disabled and without provider aliases. Evaluate an explicit XAUUSD Spot data provider with documented API coverage and licensing. If the intended instrument is GC futures instead, register it as a separate futures instrument with expiry/roll metadata and verified contract multiplier.

## Exit criteria

- Provider and plan documented for each selected instrument.
- Exact symbol and venue mapping tested with authorized credentials.
- Freshness and timezone semantics validated against provider timestamps.
- OHLC integrity and closed-candle handling covered by tests.
- Currency, contract multiplier, trading calendar and estimated transaction costs verified.
- Market-data licensing and redistribution restrictions recorded.
