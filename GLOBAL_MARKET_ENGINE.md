# Global Market Engine v1 — foundation and crypto screening

## Operating profile
- Global multi-asset discovery; mixed short-, medium- and long-term horizons.
- Horizons: short 1–10 days; medium 2–12 weeks; long 3–24 months.
- Research and paper-trading only. No live orders or wallet signing.
- Existing Market Scanner and paper ledgers remain independent.

## Initial asset universe
Configuration includes equities, ETFs, indices, crypto, FX, commodities and futures. Crypto seeds: BTC, ETH, SOL, LINK, XLM, SUI, HYPE, XMR, LEO, BAT, PEPE, BEAM and ANVL. Futures have no seed contracts until contract metadata and provider coverage are verified.

Seeds are discovery candidates, not proof that every instrument is supported or tradable. Provider-qualified identifiers, venue, quote currency and source timestamps must be retained.

## Binance crypto market data
- `global_markets.providers.binance.BinanceMarketDataClient` reads public spot OHLCV klines from Binance's market-data-only host.
- `global_markets.crypto_feed.CryptoWatchlistFeed` fetches the 13-symbol seed list at 4h and daily intervals.
- No API key, account credentials, private endpoints or order endpoints are used.
- Pair mappings are explicit. Before fetching candles, the feed checks Binance `exchangeInfo` and only requests pairs currently marked `TRADING` with Spot trading enabled. Delisted or inactive pairs are reported as unavailable; a failed listing check fails closed rather than reusing potentially stale history. Unsupported/unlisted pairs are reported as unavailable, not silently substituted.
- Candles contain open/high/low/close, base volume, quote volume, trade count, interval, open timestamp and close timestamp.
- A live GitHub Actions smoke test validates the feed and market data quality. A runtime exchange-listing check now prevents delisted/inactive pairs from returning old historical candles as if they were current. XMR/BEAM and LEO/ANVL must still be checked against the current Binance Spot listing; no substitute pair is assumed.

## Freshness and technical analysis
`global_markets.market_analysis`:
- Excludes still-forming candles from indicator calculations.
- Rejects future timestamps, stale data and insufficient history.
- Calculates RSI(14), MACD(12,26,9), SMA(20), SMA(50) and approximate annualized realized volatility.
- Produces a 0–100 technical screening score from trend, moving-average alignment, MACD and RSI.
- The score is technical-only. It is not a probability, expected return, complete opportunity rank or investment recommendation.

## Dashboard integration
The Streamlit app includes a separate **Global opportunity scanner** tab:
- On-demand fetch, cached for five minutes.
- Separate 4h tactical view and daily trend-confirmation view.
- Shows indicator values, technical screening scores, data-age checks, rejected series and unavailable provider pairs.
- Does not open, close, or modify paper positions and does not affect the existing scanner.

## Multi-timeframe crypto structure and relative strength
When both fresh, closed daily and 4h series exist, the crypto watchlist classifies:
- Confirmed trend: both technical scores >= 62.5 and both intervals have RSI >= 50 with MACD above its signal.
- Possible reversal (daily pending): daily remains weak (<= 37.5), 4h score is strong (>= 62.5), and 4h RSI >= 50 with MACD above its signal.
- Incipient recovery: daily remains weak and 4h score is strong, but RSI/MACD confirmation is incomplete.
- Timeframe divergence: daily score >= 62.5 while 4h score <= 50.
- Weakness: both scores <= 37.5.
- Mixed structure: other combinations.
Daily returns over 7 and 30 sessions are calculated from closed candles. Relative strength versus BTC is the asset return minus BTC return over the same period, expressed in percentage points. These are descriptive screening metrics, not forecasts, calibrated probabilities or trade signals. Missing BTC or insufficient history leaves relative-strength values blank.

## Multi-asset scoring contract
`global_markets.scoring.rank_candidate` accepts normalized candidate data and component scores from 0–100. Default weights: technical 35%, fundamental 30%, catalyst 15%, liquidity 10%, risk control 10%. A higher risk-control score means better-controlled risk. Missing components are excluded and remaining weights normalized; score is withheld unless at least 60% of configured weight is represented. Output includes coverage and rejection reasons; it is not a trade instruction.

The scoring primitive validates identity, supported asset class, positive price and observation timestamp. Callers should set a maximum data age appropriate to source and instrument.

## Other providers and coverage gaps
- Alpha Vantage adapter supports daily FX. The dashboard can request EUR/USD, USD/JPY, GBP/USD and USD/CHF through `FX_DAILY` when `ALPHA_VANTAGE_API_KEY` is set in hosting Secrets. One scan uses four requests and is cached for 15 minutes; this is deliberately conservative against the free-tier 25-request/day quota. The feed is on-demand and uses a five-calendar-day freshness window. FX volume is not supplied and is explicitly unavailable, not imputed as liquidity. The free-tier crypto endpoint returned a limit notice in the observed verification run; do not rely on it for crypto until verified with an authorized key/plan.
- FinancialData.Net coverage is constrained by documented plan entitlements. Symbol-directory matches do not prove price-history access.
- Index and futures coverage still require separate verified data sources.
- A daily-history feed now requests equity, ETF and commodity OHLCV from the documented FinancialData.Net endpoints. It is optional and requires `FINANCIALDATA_API_KEY` in hosting Secrets. It is on-demand, cached for 15 minutes, limited to 120 observations per instrument, and reports missing/invalid symbols individually.
- The feed uses the free daily-history endpoints where documented, but directory coverage and endpoint entitlement can still vary by symbol and account. It does not imply real-time quotes. A five-calendar-day freshness window avoids automatically rejecting normal weekend gaps; the displayed age remains visible.
- The dashboard includes technical screening for valid equity, ETF, commodity and FX daily histories. FX is a separate Alpha Vantage feed; the four-pair scan consumes four requests. Fundamentals and catalysts are not yet wired into this multi-asset dashboard; complete opportunity rankings must wait for those inputs.

## Safety and operational boundaries
- Research and public market-data requests only.
- No live orders, wallet signing, API account access or real-money execution.
- Never commit provider credentials; use host-side environment secrets.
- Scores are screening aids, not investment advice or expected returns.
- Validate data licensing and redistribution terms before exposing market data.
- Do not connect global technical scores to automatic paper entries without a separate review of sizing, risk rules and portfolio compatibility.

## Tests
```bash
python -m py_compile app.py global_markets/*.py global_markets/providers/*.py
python -m unittest discover -s tests -p 'test_global_market_*.py' -v
python -m unittest discover -s tests -p 'test_binance_adapter.py' -v
python -m unittest discover -s tests -p 'test_crypto_feed.py' -v
python -m unittest discover -s tests -p 'test_market_analysis.py' -v
```

## Next increment
Validate live endpoint access for the equity, ETF and commodity daily-history feed across the selected symbols and account plan. Validate live FX endpoint access with an authorized key, then add asset-class-specific fundamental and catalyst features. Keep indices and futures marked as unsupported until source and contract metadata are validated.

## Mobile crypto diagnostics
The RSI detail and BTC-relative-strength metrics are displayed in separate narrow tables. Rejected series and unavailable provider requests use human-readable Catalan labels in the primary view; original provider error codes remain available in a collapsed technical-details section for diagnosis.

## Comparative chart and structure transitions
Daily analysis exposes the last 31 closed daily candles rebased to 100 at the first observation, only when sufficient history exists. The dashboard plots selected assets on the same normalized scale for relative performance comparison. Consecutive structure categories are compared within the active Streamlit session; category changes are shown as transitions, and a move into confirmed trend is highlighted. This transition history is session-scoped and resets when the session restarts; it is not a persisted alert service or an instruction to trade.

## Technical alerts and durable history
The crypto scanner generates informational events for:
- Entry into a confirmed multi-timeframe structure.
- RSI crossing above 50 on the daily or 4h closed candle.
- Bullish MACD/signal-line crossover on the daily or 4h closed candle.
- Positive relative strength versus BTC on both 7d and 30d windows.

Alerts are deduplicated by asset, event type and relevant candle close. They never create or modify paper positions. Previous RSI and MACD values are calculated from closed candles only.

For durable history, configure Supabase and create this separate table in the Supabase SQL editor:
```sql
create table if not exists public.market_alert_events (
  id bigint generated by default as identity primary key,
  dedupe_key text not null unique,
  event_type text not null,
  asset text not null,
  label text not null,
  detail text not null,
  daily_close timestamptz,
  four_hour_close timestamptz,
  created_at timestamptz not null default now()
);
alter table public.market_alert_events enable row level security;
```
The app accesses this table using the existing server-side Supabase service-role secret. Do not expose that key in browser code or commit it to GitHub. Without the table or Supabase configuration, the app explicitly falls back to session-only alert history.
