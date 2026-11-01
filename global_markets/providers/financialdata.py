"""Read-only FinancialData.Net HTTP adapter with bounded retries and pagination.

The adapter is intentionally opt-in. It does not place orders and does not
assume that a symbol is covered by the connected subscription.
"""
from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import requests


BASE_URL = "https://financialdata.net/api/v1"
ALLOWED_ENDPOINTS = {
    "stock-symbols", "international-stock-symbols", "etf-symbols",
    "commodity-symbols", "futures-symbols", "crypto-symbols", "forex-symbols",
    "stock-prices", "international-stock-prices", "etf-prices",
    "commodity-prices", "futures-prices", "crypto-prices", "forex-prices",
    "index-prices", "stock-quotes", "crypto-quotes", "forex-quotes",
}


class FinancialDataError(RuntimeError):
    """Provider request or response error."""


class FinancialDataClient:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        max_pages: int = 10,
        sleep=time.sleep,
        random_fn=random.random,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("api_key is required")
        if (
            not math.isfinite(timeout) or timeout <= 0
            or not math.isfinite(backoff_seconds) or backoff_seconds < 0
            or max_retries < 0 or max_pages < 1
        ):
            raise ValueError("invalid timeout, retry, backoff or pagination limits")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.max_pages = max_pages
        self.sleep = sleep
        self.random_fn = random_fn

    def get(self, endpoint: str, params: Mapping[str, Any] | None = None) -> Any:
        if endpoint not in ALLOWED_ENDPOINTS:
            raise ValueError("unsupported FinancialData.Net endpoint")
        query = dict(params or {})
        query["key"] = self.api_key
        url = f"{BASE_URL}/{endpoint}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=query, timeout=self.timeout)
                if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
                    if attempt >= self.max_retries:
                        raise FinancialDataError(f"provider temporarily unavailable (HTTP {response.status_code})")
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(float(retry_after), 30.0) if retry_after else min(
                            self.backoff_seconds * (2 ** attempt) + self.random_fn() * 0.25, 30.0
                        )
                    except (TypeError, ValueError):
                        delay = min(self.backoff_seconds * (2 ** attempt), 30.0)
                    self.sleep(max(0.0, delay))
                    continue
                if response.status_code >= 400:
                    raise FinancialDataError(f"provider returned HTTP {response.status_code}")
                try:
                    return response.json()
                except ValueError as exc:
                    raise FinancialDataError("provider returned invalid JSON") from exc
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FinancialDataError("provider request failed after bounded retries") from exc
                delay = min(self.backoff_seconds * (2 ** attempt) + self.random_fn() * 0.25, 30.0)
                self.sleep(delay)
        raise FinancialDataError("provider request failed")

    def list_symbols(self, asset_class: str) -> list[dict]:
        endpoints = {
            "equity": ("stock-symbols", "international-stock-symbols"),
            "etf": ("etf-symbols",),
            "commodity": ("commodity-symbols",),
            "future": ("futures-symbols",),
            "crypto": ("crypto-symbols",),
            "forex": ("forex-symbols",),
        }
        if asset_class not in endpoints:
            raise ValueError("symbol directory not supported for this asset class")
        results: list[dict] = []
        seen: set[str] = set()
        for endpoint in endpoints[asset_class]:
            for page in range(self.max_pages):
                payload = self.get(endpoint, {"offset": page * 500})
                if not isinstance(payload, list):
                    raise FinancialDataError("symbol endpoint returned a non-list payload")
                for item in payload:
                    if isinstance(item, dict):
                        symbol = item.get("trading_symbol")
                        key = str(symbol).upper() if symbol is not None else repr(item)
                        if key not in seen:
                            seen.add(key)
                            results.append(item)
                if len(payload) < 500:
                    break
        return results

    def find_symbols(self, asset_class: str, requested: list[str]) -> dict[str, dict | None]:
        """Return exact, case-insensitive symbol matches; never guess aliases."""
        requested_map = {symbol.upper(): symbol for symbol in requested}
        directory = self.list_symbols(asset_class)
        matches: dict[str, dict | None] = {symbol: None for symbol in requested}
        for item in directory:
            symbol = item.get("trading_symbol")
            if isinstance(symbol, str) and symbol.upper() in requested_map:
                matches[requested_map[symbol.upper()]] = item
        return matches

    @staticmethod
    def normalize_quote(
        record: Mapping[str, Any], *, asset_class: str,
        source: str = "financialdata.net", source_timezone: timezone | None = None,
    ) -> dict:
        """Normalize a quote while preserving the provider's original timestamp."""
        symbol = record.get("trading_symbol")
        price = record.get("price")
        timestamp = record.get("time")
        if not symbol or price is None or not timestamp:
            raise FinancialDataError("quote is missing symbol, price or source timestamp")
        try:
            numeric_price = float(price)
        except (TypeError, ValueError, OverflowError) as exc:
            raise FinancialDataError("quote price is invalid") from exc
        if not math.isfinite(numeric_price) or numeric_price <= 0:
            raise FinancialDataError("quote price must be positive")
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(str(timestamp), fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise FinancialDataError("unsupported provider timestamp format")
        # Crypto/FX quote endpoints document UTC; stock quotes document EST.
        # Other naive timestamps require an explicit timezone to avoid false UTC conversion.
        if parsed.tzinfo is None:
            if source_timezone is None:
                if asset_class in {"crypto", "forex"}:
                    source_timezone = timezone.utc
                elif asset_class == "equity":
                    source_timezone = timezone(timedelta(hours=-5))
                else:
                    raise FinancialDataError("source_timezone is required for this asset class")
            parsed = parsed.replace(tzinfo=source_timezone)
        observed = parsed.astimezone(timezone.utc)
        return {
            "asset_id": f"{source}:{asset_class}:{symbol}",
            "symbol": symbol,
            "asset_class": asset_class,
            "price": numeric_price,
            "observed_at": observed.isoformat(),
            "source_timestamp": str(timestamp),
            "source_timezone": str(source_timezone or parsed.tzinfo),
            "source": source,
        }
