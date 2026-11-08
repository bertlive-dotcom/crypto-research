# Prediction Market Intelligence (PMI) — v1 foundation

**Status:** read-only data ingestion and descriptive analytics  
**Branch:** `feature/prediction-market-intelligence-v1`

## Purpose

PMI adds a separate observation layer to MIDMarkets. It collects public prediction-market prices for selected crypto and macroeconomic events and preserves the distinction between an exchange-implied probability and a calibrated forecast.

## v1 scope

- Polymarket Gamma public API for active, unresolved market discovery.
- Polymarket CLOB public price-history endpoint for read-only historical observations.
- Normalize binary Yes/No prices, volume, liquidity, event expiry, source and timestamps.
- Classify markets into crypto, macro or other using transparent keyword rules.
- Calculate probability divergence only when an independent reference probability is supplied.
- Show missing reference data as unavailable; never substitute zero or manufacture a divergence.
- Keep sports, pop-culture and political markets out of the default dashboard view.
- No API keys, wallet connection, order placement, signing, deposits, withdrawals or live trading.

## Safety boundary

PMI is an independent observer. It does not open or close paper positions, call the Market Scanner entry path, change technical thresholds, change position sizing, or bypass portfolio risk controls. A high implied probability is not an entry signal.

The first version is not a calibrated prediction model. Polymarket prices can be affected by liquidity, spreads, concentration, fees, resolution rules and participant incentives. Display volume/liquidity and source time alongside probability. Avoid interpreting thin markets as reliable consensus.

## Scheduled snapshots and staging setup

The staging database stores observations in `public.pmi_market_snapshots`. A database-native collector uses `pg_cron` and `pg_net` to request the tagged Polymarket crypto and macro event feeds every 15 minutes. A second job processes the asynchronous HTTP responses two minutes after each fetch. The processor flattens nested event markets, validates Yes/No prices, and upserts by market ID and 15-minute bucket so retries do not create duplicate snapshots.

The dashboard history reader uses a separate server-side connection. Add these values only in Streamlit hosting Secrets, pointing to the staging Supabase project:

```toml
PMI_SUPABASE_URL = "https://YOUR-STAGING-PROJECT.supabase.co"
PMI_SUPABASE_SERVICE_ROLE_KEY = "YOUR-STAGING-SERVICE-ROLE-KEY"
```

Do not use the paper-trading production credentials for PMI until staging validation is complete. The service-role key remains server-side and must never be committed.

The Gamma API's global top-volume market list can be dominated by unrelated categories. PMI therefore discovers active events through the `crypto` and `macro` tagged event feeds and then classifies individual nested markets using word-boundary keyword rules. Tag feeds can be incomplete; coverage must be monitored.

## Data model

Each normalized observation contains:
- market ID and question;
- category (crypto / macro / other);
- Yes and No implied probabilities when explicitly available;
- 24-hour or lifetime volume where supplied;
- liquidity where supplied;
- end date, update timestamp, source and market URL;
- Yes outcome token ID for optional public price-history retrieval.

The adapter requests active and unresolved markets and fails closed on malformed responses. Missing fields remain null.

## Probability divergence

`probability_divergence(market_probability, reference_probability)` returns the market-minus-reference gap in percentage points. It does not calculate a reference probability. Until a separate model or independently sourced benchmark is validated, the dashboard must show divergence as unavailable.

## Calibration metrics

The scoring module exposes Brier score and log loss for resolved binary outcomes. Metrics remain unavailable until resolved outcomes have been joined to the exact forecast snapshot taken before resolution. Do not calculate calibration from current prices or from an observation recorded after the event resolved.

## Validation

Run:

```bash
python -m py_compile prediction_markets/*.py
python -m unittest discover -s tests -p "test_prediction_markets.py" -v
```

## Next steps

1. Verify current API response shape and rate limits against official Polymarket documentation.
2. Persist time-stamped probability snapshots in a dedicated store before evaluating signal quality.
3. Add independent reference probabilities for a small, well-defined macro/crypto event set.
4. Measure calibration (Brier score / log loss), coverage, liquidity and resolution quality over a meaningful sample.
5. Only after validation, expose PMI as a non-authoritative feature to the existing Signal Engine. Paper trading requires a separate review and explicit enablement.
