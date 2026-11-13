""""Read-only EODHD daily ETF history adapter."""
from __future__ import annotations

import math
from datetime import datetime, time, timezone
from typing import Any

import requests

BASE_URL = "https://eodhd.com/api"


class EODHDError(RuntimeError):
    """Sanitized EODHD request, entitlement, or response error."""


class EODHDClient:
    def __init__(self, api_token: str, *, session: requests.Session | None = None, timeout: float = 15.0):
        if not isinstance(api_token, str) or not api_token.strip():
            raise ValueError("api_token is required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_token = api_token.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_daily_prices_with_quality(self, symbol: str, asset_class: str, *, limit: int = 120) -> dict[str, Any]:
        if asset_class != "etf":
            raise ValueError("EODHD fallback is currently restricted to ETFs")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol is required")
        if not isinstance(limit, int) or not 1 <= limit <= 365:
            raise ValueError("limit must be between 1 and 365")
        ticker = symbol.strip().upper()
        if ticker == "SPY":
            ticker = "SPY.US"
        elif "." not in ticker:
            raise ValueError("EODHD symbols must include an explicit exchange suffix")
        try:
            response = self.session.get(
                f"{BASE_URL}/eod/{ticker}",
                params={"api_token": self.api_token, "fmt": "json", "period": "d"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise EODHDError("EODHD request failed") from exc
        if response.status_code in {401, 403}:
            raise EODHDError(f"EODHD access denied (HTTP {response.status_code}); check API-key validity and plan entitlement")
        if response.status_code == 402:
            raise EODHDError("EODHD daily API quota or plan limit reached (HTTP 402)")
        if response.status_code == 404:
            raise EODHDError("EODHD ticker was not found or is not included in the plan (HTTP 404)")
        if response.status_code == 429:
            raise EODHDError("EODHD request rate limit reached (HTTP 429)")
        if response.status_code >= 400:
            raise EODHDError(f"EODHD returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EODHDError("EODHD returned invalid JSON") from exc
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or "provider returned an error")
            raise EODHDError("EODHD API error: " + message[:160])
        if not isinstance(payload, list):
            raise EODHDError("EODHD returned an unexpected daily-series payload")

        candles, rejected, seen = [], [], set()
        for index, item in enumerate(payload):
            try:
                if not isinstance(item, dict):
                    raise ValueError("record is not an object")
                day = datetime.strptime(str(item["date"]), "%Y-%m-%d").date()
                prices = {key: float(item[key]) for key in ("open", "high", "low", "close")}
                volume = float(item.get("volume") or 0)
                if any(not math.isfinite(value) or value <= 0 for value in prices.values()):
                    raise ValueError("OHLC values must be finite and positive")
                if not math.isfinite(volume) or volume < 0:
                    raise ValueError("volume must be finite and non-negative")
                if prices["high"] < max(prices["open"], prices["low"], prices["close"]):
                    raise ValueError("high is inconsistent with OHLC")
                if prices["low"] > min(prices["open"], prices["high"], prices["close"]):
                    raise ValueError("low is inconsistent with OHLC")
                if day in seen:
                    raise ValueError("duplicate observation date")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                rejected.append({"record": index, "reason": str(exc)})
                continue
            seen.add(day)
            candles.append({
                "asset_id": f"eodhd:etf:{ticker}", "symbol": ticker,
                "asset_class": "etf", "interval": "1d", "date": day.isoformat(),
                "timestamp": datetime.combine(day, time.min, tzinfo=timezone.utc).isoformat(),
                "close_timestamp": datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc).isoformat(),
                **prices, "volume": volume, "source": "eodhd",
                "source_timezone": "UTC-date-label; exchange close time not specified by adapter",
            })
        candles.sort(key=lambda row: row["timestamp"])
        # Providers may return oldest-first or newest-first. Always retain the\n        # most recent requested observations after chronological normalization.\n        candles = candles[-limit:]\n        if not candles:
            raise EODHDError("EODHD returned no valid exact-symbol daily ETF records")
        return {"candles": candles, "rejected_records": rejected, "source_records": len(payload)}
