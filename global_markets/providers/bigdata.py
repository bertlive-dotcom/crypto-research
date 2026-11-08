"""Bigdata.com Search API adapter.

Uses the official REST endpoint and X-API-KEY header. Credentials must be
provided by the hosting environment (BIGDATA_API_KEY), never committed.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

import requests


class BigdataAPIError(RuntimeError):
    """Raised when Bigdata.com cannot complete a request."""


class BigdataClient:
    BASE_URL = "https://api.bigdata.com"
    SEARCH_PATH = "/v1/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: tuple[float, float] = (5.0, 30.0),
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("BIGDATA_API_KEY", "")).strip()
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> Mapping[str, Any]:
        """Run a natural-language search and return the provider payload."""
        if not self.configured:
            raise BigdataAPIError("BIGDATA_API_KEY is not configured.")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        url = f"{self.BASE_URL}{self.SEARCH_PATH}"
        try:
            response = self.session.post(
                url,
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={"query": {"text": query.strip()}},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise BigdataAPIError(f"Bigdata request failed: {exc.__class__.__name__}") from exc

        if response.status_code == 401 or response.status_code == 403:
            raise BigdataAPIError(
                "Bigdata rejected the credentials or this API entitlement (HTTP "
                f"{response.status_code}). Check the key and account permissions."
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            suffix = f" Retry after {retry_after} seconds." if retry_after else ""
            raise BigdataAPIError(f"Bigdata rate limit reached (HTTP 429).{suffix}")
        if not response.ok:
            raise BigdataAPIError(f"Bigdata returned HTTP {response.status_code}.")

        try:
            payload = response.json()
        except ValueError as exc:
            raise BigdataAPIError("Bigdata returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise BigdataAPIError("Bigdata returned an unexpected response format.")
        return payload
