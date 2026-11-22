"""Private, read-only HTTP transport for the assistant market overview.

Run with: uvicorn assistant.http_api:app
Requires CRYPTO_RESEARCH_INTERNAL_API_TOKEN to be configured.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from assistant.service import AssistantServiceError, ReadOnlyAssistantService
from global_markets.crypto_feed import CryptoWatchlistFeed

app = FastAPI(
    title="Crypto Research Internal Read API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
service = ReadOnlyAssistantService(feed=CryptoWatchlistFeed())


def require_internal_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("CRYPTO_RESEARCH_INTERNAL_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API authentication is not configured")
    scheme, separator, supplied = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid service credentials")


@app.get("/internal/v1/assistant/crypto-overview", dependencies=[Depends(require_internal_token)])
def crypto_overview(
    symbols: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(default=200, ge=35, le=1000),
) -> dict:
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    if not requested or len(requested) > len(__import__("global_markets.crypto_feed", fromlist=["BINANCE_SPOT_PAIRS"]).BINANCE_SPOT_PAIRS):
        raise HTTPException(status_code=422, detail="Invalid number of requested symbols")
    if len(requested) != len(set(requested)):
        raise HTTPException(status_code=422, detail="Symbols must be unique")
    try:
        return service.crypto_overview(requested, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported market symbol or request") from exc
    except AssistantServiceError as exc:
        raise HTTPException(status_code=503, detail="Market data service unavailable") from exc
