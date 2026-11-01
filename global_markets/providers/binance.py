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

    def get_active_spot_symbols(self) -> set[str]:
        """Return symbols currently tradable on Binance Spot."""
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
        return {
            str(item.get("symbol", "")).upper()
            for item in payload["symbols"]
            if isinstance(item, dict)
            and item.get("status") == "TRADING"
            and item.get("isSpotTradingAllowed", True) is True
        }

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 500) -> list[dict[str, Any]]:
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
                params={"symbol": pair, "interval": interval, "limit": limit},
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
