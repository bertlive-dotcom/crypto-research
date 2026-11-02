"""Read-only Binance public market-data adapter.

Uses the market-data-only host; no API key or account permissions are needed.
This adapter fetches spot OHLCV candles only and never submits orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
EXCHANGE_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"


class BinanceMarketDataError(RuntimeError):
    """Sanitized Binance market-data or rate-limit error."""


class BinanceMarketDataClient:
    def __init__(self, *, session: requests.Session | None = None, timeout: float = 15.0):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_spot_symbol_status(self) -> dict[str, dict[str, Any]]:
        """Return current and inactive Binance symbol metadata for diagnosis."""
        try:
            response = self.session.get(EXCHANGE_INFO_URL, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise BinanceMarketDataError("Binance exchange-info request failed") from exc
        except ValueError as exc:
            raise BinanceMarketDataError("Binance returned invalid exchange-info JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise BinanceMarketDataError("Binance returned an unexpected exchange-info response")
        result = {}
        for item in payload["symbols"]:
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).upper()
            result[symbol] = {
                "status": str(item.get("status", "UNKNOWN")).upper(),
                "spot_allowed": item.get("isSpotTradingAllowed", True) is True,
                "base_asset": item.get("baseAsset"),
                "quote_asset": item.get("quoteAsset"),
            }
        return result

    def get_active_spot_symbols(self) -> set[str]:
        """Return symbols currently tradable on Binance Spot."""
        return {
            symbol for symbol, details in self.get_spot_symbol_status().items()
            if details["status"] == "TRADING" and details["spot_allowed"]
        }

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 500, *, end_time_ms: int | None = None) -> list[dict[str, Any]]:
        pair = symbol.strip().upper()
        if not pair or not pair.isalnum():
            raise ValueError("symbol must contain only letters and digits")
        if interval not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"}:
            raise ValueError("unsupported Binance kline interval")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            response = self.session.get(
                BASE_URL,
                params={**{"symbol": pair, "interval": interval, "limit": limit},
                        **({"endTime": int(end_time_ms)} if end_time_ms is not None else {})},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                raise BinanceMarketDataError("Binance public market-data rate limit reached") from exc
            raise BinanceMarketDataError("Binance public market-data request failed") from exc
        except ValueError as exc:
            raise BinanceMarketDataError("Binance returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise BinanceMarketDataError("Binance returned an unexpected kline response")
        rows = []
        try:
            for candle in payload:
                if not isinstance(candle, list) or len(candle) < 11:
                    raise ValueError("invalid candle shape")
                timestamp = datetime.fromtimestamp(int(candle[0]) / 1000, tz=timezone.utc)
                close_timestamp = datetime.fromtimestamp(int(candle[6]) / 1000, tz=timezone.utc)
                rows.append({
                    "symbol": pair,
                    "asset_class": "crypto",
                    "date": timestamp.date().isoformat(),
                    "timestamp": timestamp.isoformat(),
                    "close_timestamp": close_timestamp.isoformat(),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "quote_volume": float(candle[7]),
                    "trades": int(candle[8]),
                    "source": "binance",
                    "interval": interval,
                })
        except (TypeError, ValueError, OverflowError, IndexError) as exc:
            raise BinanceMarketDataError("Binance returned malformed kline data") from exc
        if not rows:
            raise BinanceMarketDataError("Binance returned no kline observations")
        return rows


    def get_klines_history(self, symbol: str, interval: str = "1d", total_limit: int = 5000) -> list[dict[str, Any]]:
        """Fetch up to total_limit candles by paging backwards through Binance Spot.

        Pages contain at most 1000 candles. Results are deduplicated and returned
        oldest-to-newest; callers must still remove the currently forming candle.
        """
        if not 1 <= total_limit <= 10000:
            raise ValueError("total_limit must be between 1 and 10000")
        collected: dict[str, dict[str, Any]] = {}
        end_time_ms = None
        while len(collected) < total_limit:
            page_limit = min(1000, total_limit - len(collected))
            page = self.get_klines(
                symbol, interval=interval, limit=page_limit, end_time_ms=end_time_ms
            )
            if not page:
                break
            for row in page:
                collected[row["timestamp"]] = row
            oldest = min(
                datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp()
                for row in page
            )
            next_end_time_ms = int(oldest * 1000) - 1
            if end_time_ms is not None and next_end_time_ms >= end_time_ms:
                raise BinanceMarketDataError("Binance kline pagination did not advance")
            end_time_ms = next_end_time_ms
            if len(page) < page_limit:
                break
        return sorted(collected.values(), key=lambda row: row["timestamp"])[-total_limit:]


def last_closed_candle(candles: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Return the newest fully closed candle, never the still-forming interval."""
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    closed = []
    for candle in candles:
        raw_close_time = candle.get("close_timestamp")
        if not raw_close_time:
            continue
        try:
            close_time = datetime.fromisoformat(str(raw_close_time).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        if close_time <= reference_time:
            closed.append((close_time, candle))
    return max(closed, key=lambda item: item[0])[1] if closed else None
