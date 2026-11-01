# Global Market Engine v1 — foundation

## Selected operating profile
- Scope: global multi-asset discovery.
- Style: mixed short-, medium- and long-term opportunities.
- Horizons: short 1–10 days; medium 2–12 weeks; long 3–24 months.
- Execution: research and paper-trading only. No live orders or wallet signing.

## Initial asset universe

Configuration seeds equities, ETFs, indices, crypto, FX and commodities. The
crypto seed universe contains BTC, ETH, SOL, LINK, XLM, SUI, HYPE, XMR, LEO,
BAT, PEPE, BEAM and ANVL. Futures remain enabled as an asset class but have no
seed symbols until provider coverage and contract metadata are verified.

Seeds are discovery candidates, not a claim that every instrument is supported
or currently tradable. Provider-qualified identifiers, venue, quote currency
and source timestamps must be retained before ranking.

## Ranking contract

global_markets.scoring.rank_candidate accepts normalized candidate data and
component scores from 0–100. Default weights: technical 35%, fundamental 30%,
catalyst 15%, liquidity 10%, risk control 10%. A higher risk-control score means
better-controlled risk. Missing components are excluded and remaining weights
normalized, but a score is withheld unless at least 60% of configured weight is
represented. Output includes coverage and rejection reasons; it is not a trade
instruction.

The scoring primitive validates identity, supported asset class, positive price
and observation timestamp. Callers may set a maximum data age appropriate to
the source and instrument.

## Data-provider integration status

### Binance public spot crypto feed
- `global_markets.providers.binance.BinanceMarketDataClient` reads public
  spot OHLCV klines from Binance's market-data-only host.
- `global_markets.crypto_feed.CryptoWatchlistFeed` connects this adapter to the
  global crypto seed universe and supports daily and 4-hour candles.
- No API key, account credentials, private endpoints or order endpoints are used.
- Pair mappings are explicit. Unsupported/unlisted pairs are reported in
  `unavailable`; they are not silently replaced.
- Results include OHLC, base volume, quote volume, trade count, interval and
  source. The feed returns per-pair failures so one unavailable token does not
  discard successful market data.
- This is a read-only data feed. It is not yet a signal generator, ranking
  integration, persistence job or UI view.

### Other providers
- Alpha Vantage adapter supports daily FX and has a confirmed EUR/USD response.
  The free tier returned a limit notice for the crypto daily endpoint in the
  observed verification run; do not rely on it for crypto.
- FinancialData.Net coverage is constrained by documented plan entitlements.
  Symbol-directory matches do not prove price-history access.
- Index and futures coverage still require separate verified data sources.

## Recommended integration sequence

1. Complete provider symbol/coverage discovery and persist a canonical instrument catalogue.
2. Connect normalized provider data to feature builders and freshness checks.
3. Add technical, fundamental and catalyst feature builders by asset class; never fabricate unavailable metrics.
4. Rank only candidates with sufficient score coverage and acceptable data freshness.
5. Add paper-trading simulations per asset class after contract sizing, trading hours, fees, currency conversion and shorting rules are modeled.

## Safety and operational boundaries
- Existing crypto scanner and paper ledger remain unchanged.
- The new Binance feed performs read-only public market-data requests only.
- Never commit provider credentials; use host-side environment secrets.
- Scores are screening aids, not investment advice or expected returns.
- Validate data licensing and redistribution terms before exposing market data.

## Tests
Run:
- `python -m unittest discover -s tests -p 'test_global_market_*.py' -v`
- `python -m unittest discover -s tests -p 'test_binance_adapter.py' -v`
- `python -m unittest discover -s tests -p 'test_crypto_feed.py' -v`

## Next increment

Connect the feed to the global market UI and a bounded refresh/cache layer,
then add technical feature calculations and opportunity ranking. Do not enable
automated entries or live execution.
