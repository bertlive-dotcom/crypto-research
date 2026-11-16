"""Read-only adapter for the Bitpanda Public API v2."""
from __future__ import annotations

from typing import Any
import requests


class BitpandaAPIError(RuntimeError):
    """Raised for Bitpanda API or response errors."""


class BitpandaClient:
    BASE_URL = "https://api.public.bitpanda.com/v1"

    def __init__(self, api_key: str, timeout: int = 20, session=None):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ValueError("BITPANDA_API_KEY is required.")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "x-api-key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "crypto-research-portfolio-intelligence/1.0",
        })

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            response = self.session.get(
                self.BASE_URL + path, params=params or {}, timeout=self.timeout
            )
            if response.status_code == 401:
                raise BitpandaAPIError("Bitpanda API key is invalid or expired (401).")
            if response.status_code == 403:
                raise BitpandaAPIError(
                    "Bitpanda denied access (403). Check that the key has the required read scopes."
                )
            if response.status_code == 429:
                raise BitpandaAPIError("Bitpanda rate limit reached (429). Retry later.")
            response.raise_for_status()
            payload = response.json()
        except BitpandaAPIError:
            raise
        except requests.RequestException as exc:
            raise BitpandaAPIError("Bitpanda request failed: " + str(exc)) from exc
        except ValueError as exc:
            raise BitpandaAPIError("Bitpanda returned invalid JSON.") from exc

        if isinstance(payload, dict) and payload.get("error"):
            raise BitpandaAPIError(str(payload["error"]))
        return payload

    @staticmethod
    def _items(payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if not isinstance(payload, dict):
            return []
        data = payload.get("data", payload.get("items", []))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("items", "holdings", "positions", "operations", "datapoints"):
                value = data.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
        return []

    @staticmethod
    def _next_cursor(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        candidates = [payload, payload.get("pagination", {}), payload.get("meta", {})]
        for item in candidates:
            if isinstance(item, dict):
                cursor = item.get("nextCursor") or item.get("next_cursor")
                if cursor:
                    return str(cursor)
        return None

    def get_holdings(self) -> list[dict]:
        return self._items(self._get("/portfolio/holdings"))

    def get_history(self, timeframe: str = "MONTH") -> list[dict]:
        allowed = {"DAY", "WEEK", "MONTH", "SIX_MONTH", "YEAR"}
        if timeframe not in allowed:
            raise ValueError("Unsupported Bitpanda portfolio timeframe.")
        return self._items(self._get("/portfolio/history", {"timeframe": timeframe}))

    def get_operations(self, max_pages: int = 5, page_size: int = 100) -> list[dict]:
        rows, cursor = [], None
        for _ in range(max(1, min(int(max_pages), 20))):
            params = {"pageSize": max(1, min(int(page_size), 100))}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/operations", params)
            rows.extend(self._items(payload))
            cursor = self._next_cursor(payload)
            if not cursor:
                break
        return rows

    def get_earn_configs(self, max_pages: int = 5) -> list[dict]:
        rows, cursor = [], None
        for _ in range(max(1, min(int(max_pages), 20))):
            params = {"pageSize": 250}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/earn/configs", params)
            rows.extend(self._items(payload))
            cursor = self._next_cursor(payload)
            if not cursor:
                break
        return rows
