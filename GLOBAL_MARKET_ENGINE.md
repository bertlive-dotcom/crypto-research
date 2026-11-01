# Global Market Engine v1 — foundation

## Selected operating profile
- Scope: global multi-asset discovery.
- Style: mixed short-, medium- and long-term opportunities.
- Horizons: short 1–10 days; medium 2–12 weeks; long 3–24 months.
- Execution: research and paper-trading only. No live orders or wallet signing.

## Initial asset universe

Configuration seeds equities, ETFs, indices, crypto, FX and commodities. Futures
are enabled as an asset class but have no seed symbols until provider coverage and
contract metadata are verified. Seeds are examples, not a claim that every ticker
is supported or currently tradable. Normalize each instrument with a stable
provider-qualified asset_id, symbol, asset class, venue, quote currency and
observation timestamp before ranking.

## Ranking contract

global_markets.scoring.rank_candidate accepts normalized candidate data and
component scores from 0–100. Default weights: technical 35%, fundamental 30%,
catalyst 15%, liquidity 10%, risk control 10%. A higher risk-control score means
better-controlled risk. Missing components are excluded and remaining weights
normalized, but a score is withheld unless at least 60% of configured weight is
represented. Output includes coverage and rejection reasons; it is not a trade
instruction.

The scoring primitive validates identity, supported asset class, positive price
and observation timestamp. Callers may set a maximum data age appropriate to the
source and instrument. It deliberately does not impose one freshness limit across
markets with different trading hours and update frequencies.

## Data-provider integration status

This increment is provider-agnostic. It does not yet call FinancialData.Net,
Twelve Data, CoinMarketCap or Binance for global discovery. Provider adapters
must verify instrument coverage, endpoint entitlements, timestamp semantics,
rate limits, pagination and licensing. The previously reviewed FinancialData.Net
Python SDK should not be used in a long-running worker until its unbounded retry
and missing request-timeout behavior are addressed or safely wrapped.

Recommended integration sequence:
1. Add provider symbol/coverage discovery and persist a canonical instrument catalogue.
2. Add bounded-timeout, bounded-retry adapters with explicit source timestamps and provenance.
3. Add technical, fundamental and catalyst feature builders by asset class; never fabricate unavailable metrics.
4. Rank only candidates with sufficient score coverage and acceptable data freshness.
5. Add paper-trading simulations per asset class after contract sizing, trading hours, fees, currency conversion and shorting rules are modeled.

## Safety and operational boundaries
- Existing crypto scanner and paper ledger remain unchanged.
- This module performs no network calls and cannot submit orders.
- Never commit provider credentials; use host-side environment secrets.
- Scores are screening aids, not investment advice or expected returns.
- Validate data licensing and redistribution terms before exposing market data.

## Tests
Run: python -m unittest discover -s tests -p 'test_global_market_scoring.py' -v

## Next increment

Next: provider coverage audit and adapter contract. Do not enable automated
entries across equities, ETFs, futures or FX until market-specific trading and
risk mechanics have been tested independently.