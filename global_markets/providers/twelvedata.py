"""Read-only Twelve Data daily ETF history adapter.

Uses the existing TWELVE_DATA_API_KEY secret. ETF identity and exchange
timezone are validated from provider metadata; no entitlement is inferred.
"""
from __future__ import annotations

import math
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


BASE_URL = "https://api.twelvedata.com"


class TwelveDataError(RuntimeError):
    """Provider request, entitlement, or response error."""


class TwelveDataClient:
    def __init__(
        self, api_key: str, *, session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key is required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_daily_prices_with_quality(self, symbol: str, asset_class: str, *, limit: int = 120) -> dict[str, Any]:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        if asset_class != "etf":
            raise ValueError("Twelve Data fallback is currently restricted to ETFs")
        if not isinstance(limit, int) or not 35 <= limit <= 300:
            raise ValueError("limit must be between 35 and 300")
        try:
            response = self.session.get(
                f"{BASE_URL}/time_series",
                params={
                    "symbol": symbol.strip().upper(),
                    "interval": "1day",
                    "outputsize": limit,
                    "timezone": "Exchange",
                    "apikey": self.api_key,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TwelveDataError("Twelve Data request failed") from exc
        if response.status_code in {401, 403}:
            raise TwelveDataError(f"Twelve Data access denied (HTTP {response.status_code}); check API-key validity and plan entitlement")
        if response.status_code == 429:
            raise TwelveDataError("Twelve Data rate limit reached (HTTP 429)")
        if response.status_code >= 400:
            raise TwelveDataError(f"Twelve Data returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TwelveDataError("Twelve Data returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TwelveDataError("Twelve Data returned an unexpected payload")
        if payload.get("status") == "error" or "code" in payload and "values" not in payload:
            code = payload.get("code")
            safe_code = str(code)[:24] if code is not None else "unknown"
            raise TwelveDataError(f"Twelve Data API error (code {safe_code}); verify symbol, quota and plan entitlement")

        meta = payload.get("meta")
        values = payload.get("values")
        if not isinstance(meta, dict) or not isinstance(values, list):
            raise TwelveDataError("Twelve Data response is missing ETF metadata or time-series values")
        returned_symbol = str(meta.get("symbol", "")).strip().upper()
        returned_type = str(meta.get("type", "")).strip().lower()
        if returned_symbol != symbol.strip().upper():
            raise TwelveDataError("Twelve Data returned a different symbol than requested")
        if returned_type != "etf":
            raise TwelveDataError("Twelve Data metadata does not identify the requested instrument as an ETF")
        timezone_name = meta.get("exchange_timezone")
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise TwelveDataError("Twelve Data ETF metadata is missing exchange_timezone")
        try:
            exchange_tz = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise TwelveDataError("Twelve Data returned an unsupported exchange timezone") from exc

        candles, rejected = [], []
        seen_dates = set()
        for index, item in enumerate(values[:limit]):
            try:
                if not isinstance(item, dict):
                    raise ValueError("record is not an object")
                day = datetime.strptime(str(item["datetime"]), "%Y-%m-%d").date()
                prices = {key: float(item[key]) for key in ("open", "high", "low", "close")}
                volume = float(item.get("volume") or 0)
                if any(not math.isfinite(v) or v <= 0 for v in prices.values()):
                    raise ValueError("OHLC values must be finite and positive")
                if not math.isfinite(volume) or volume < 0:
                    raise ValueError("volume must be finite and non-negative")
                if prices["high"] < max(prices["open"], prices["low"], prices["close"]):
                    raise ValueError("high is inconsistent with OHLC")
                if prices["low"] > min(prices["open"], prices["high"], prices["close"]):
                    raise ValueError("low is inconsistent with OHLC")
                if day in seen_dates:
                    raise ValueError("duplicate observation date")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                rejected.append({"record": index, "reason": str(exc)})
                continue
            seen_dates.add(day)
            opened = datetime.combine(day, time.min, tzinfo=exchange_tz)
            closed = datetime.combine(day, time(16, 0), tzinfo=exchange_tz)
            candles.append({
                "asset_id": f"twelve_data:etf:{symbol.strip().upper()}",
                "symbol": symbol.strip().upper(), "asset_class": "etf", "interval": "1d",
                "date": day.isoformat(),
                "timestamp": opened.astimezone(timezone.utc).isoformat(),
                "close_timestamp": closed.astimezone(timezone.utc).isoformat(),
                **prices, "volume": volume, "source": "twelve_data",
                "source_timezone": timezone_name,
            })
        candles.sort(key=lambda row: row["timestamp"])
        if not candles:
            raise TwelveDataError("Twelve Data returned no valid exact-symbol ETF records")
        return {"candles": candles, "rejected_records": rejected, "source_records": min(len(values), limit)}
