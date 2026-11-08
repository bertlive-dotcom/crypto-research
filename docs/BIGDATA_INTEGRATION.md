# Bigdata.com integration — Phase 1

## Scope

This phase adds a small server-side adapter for Bigdata.com's Search REST API.
It does not change existing market-data providers, technical scoring, scanner
rules, paper-trading state, or order execution.

Official API documentation:
- https://docs.bigdata.com/api-rest/introduction
- https://docs.bigdata.com/api-rest/authentication

## Credential setup

Create an API key in the Bigdata Developer Platform and add it to the hosting
provider's secret/environment-variable settings:

`BIGDATA_API_KEY`

Never paste the key into source code, Streamlit UI, GitHub commits, issue
comments, logs, screenshots, or this chat. If a key is exposed, revoke it and
create a replacement.

## API behavior

- Base URL: `https://api.bigdata.com`
- Search endpoint: `POST /v1/search`
- Authentication: `X-API-KEY` request header
- Request body: `{"query": {"text": "<natural-language query>"}}`
- The adapter uses explicit connect/read timeouts and returns the raw JSON
  payload for a later presentation layer.
- HTTP 401/403, 429, network failures, and invalid response payloads fail
  explicitly. The adapter does not retry automatically or hide quota errors.

## Hosting

Add `BIGDATA_API_KEY` in the deployed app's Secrets / Environment Variables.
For Streamlit Community Cloud, use App settings → Secrets. For Render, use the
service's Environment settings. Do not add it to GitHub Actions unless a
workflow specifically needs it.

## Validation

Run:

```bash
python -m unittest discover -s tests -p 'test_bigdata_adapter.py' -v
python -m py_compile global_markets/providers/bigdata.py
```

The first live API call should be performed only after the account's API
entitlement, applicable usage limits, and permitted application/data
redistribution use have been confirmed with Bigdata.com.

## Next phase

Add a dedicated Market Intelligence view that presents cited search results,
publication timestamps, source URLs, and retrieval time. Keep Bigdata narrative
research separate from quote/price feeds and do not use it as a substitute for
validated market prices.
