# AI CORE internal read-only market API

## Scope

This optional FastAPI transport exposes only the existing read-only assistant crypto overview. It does not replace the Streamlit dashboard and does not expose scanner writes, paper-trading ledgers, exchange account access or order execution.

## Endpoint

GET /internal/v1/assistant/crypto-overview?symbols=BTCUSD,ETHUSD&limit=200

- Requires an Authorization: Bearer token header.
- Reads the expected token from CRYPTO_RESEARCH_INTERNAL_API_TOKEN.
- Fails closed with HTTP 503 if the token is not configured.
- Supports canonical crypto watchlist symbols only; duplicates are rejected.
- Limit is bounded to 35–1000 candles.
- Calls ReadOnlyAssistantService.crypto_overview() and returns its read-only payload.
- API documentation endpoints are disabled for this internal service.

## Run locally

Install the optional API dependency set:

python -m pip install -r requirements-api.txt

Set CRYPTO_RESEARCH_INTERNAL_API_TOKEN in the server environment, then run:

uvicorn assistant.http_api:app --host 127.0.0.1 --port 8010

For a deployed service, bind only to a private network or enforce service-to-service authentication at the network boundary. Do not expose this endpoint publicly. Do not place the token in a client application, source control, or logs.

## Validation

The API unit tests mock the underlying read service. They verify authentication, fail-closed configuration, canonical symbol validation and read-only payload passthrough. No live Binance request or database operation is performed by the tests.
