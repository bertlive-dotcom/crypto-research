"""Read-only Alpha Vantage adapter for daily FX and crypto history.

Free-tier use is deliberately daily/historical. The adapter does not poll
intraday endpoints, place orders, or retry soft-throttling responses.
"""
from __future__ import annotations

from typing import Any

import requests

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageError(RuntimeError):
    """Sanitized provider, entitlement, or rate-limit error."""


class AlphaVantageRateLimitError(AlphaVantageError):
    """Provider explicitly reported a request-rate limit."""


class AlphaVantageClient:
    def __init__(self, api_key: str, *, session: requests.Session | None = None, timeout: float = 15.0):
        if not api_key or not api_key.strip():
            raise ValueError("api_key is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def _query(self, function: str, **params: Any) -> dict:
        try:
            response = self.session.get(
                BASE_URL,
                params={"function": function, **params, "apikey": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise AlphaVantageError("Alpha Vantage request failed") from exc
        except ValueError as exc:
            raise AlphaVantageError("Alpha Vantage returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AlphaVantageError("Alpha Vantage returned an unexpected response")
        if "Note" in payload:
            raise AlphaVantageRateLimitError("Alpha Vantage request rate limit reached")
        if "Information" in payload:
            raise AlphaVantageError("Alpha Vantage plan entitlement or request-frequency notice")
        if "Error Message" in payload:
            raise AlphaVantageError("Alpha Vantage rejected the requested function or symbol")
        return payload

    @staticmethod
    def _ohlc_rows(series: Any, symbol: str, asset_class: str) -> list[dict]:
        if not isinstance(series, dict):
            raise AlphaVantageError("Alpha Vantage daily time series is missing")
        rows = []
        for date, values in series.items():
            if not isinstance(values, dict):
                continue
            row = {"symbol": symbol, "asset_class": asset_class, "date": date}
            for field, prefix in (("open", "1. "), ("high", "2. "), ("low", "3. "), ("close", "4. ")):
                raw = next((v for k, v in values.items() if k.startswith(prefix)), None)
                try:
                    row[field] = float(raw)
                except (TypeError, ValueError) as exc:
                    raise AlphaVantageError("Alpha Vantage OHLC field is missing or invalid") from exc
            try:
                from datetime import date as date_type, datetime, time, timezone
                parsed_date = date_type.fromisoformat(date)
            except (TypeError, ValueError) as exc:
                raise AlphaVantageError("Alpha Vantage returned an invalid observation date") from exc
            if any(row[field] <= 0 for field in ("open", "high", "low", "close")):
                raise AlphaVantageError("Alpha Vantage returned non-positive OHLC values")
            if row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(row["open"], row["close"], row["high"]):
                raise AlphaVantageError("Alpha Vantage returned inconsistent OHLC values")
            row.update({
                "timestamp": datetime.combine(parsed_date, time.min, tzinfo=timezone.utc).isoformat(),
                "close_timestamp": datetime.combine(parsed_date, time(23, 59, 59), tzinfo=timezone.utc).isoformat(),
                "source": "alpha_vantage", "interval": "1d",
                "volume": 0.0, "volume_available": False,
            })
            rows.append(row)
        if not rows:
            raise AlphaVantageError("Alpha Vantage returned no daily observations")
        return sorted(rows, key=lambda row: row["timestamp"])

    def get_fx_daily(self, from_currency: str, to_currency: str) -> list[dict]:
        base, quote = from_currency.upper(), to_currency.upper()
        payload = self._query("FX_DAILY", from_symbol=base, to_symbol=quote, outputsize="compact")
        return self._ohlc_rows(payload.get("Time Series FX (Daily)"), f"{base}{quote}", "forex")

    def get_crypto_daily(self, symbol: str, market: str = "USD") -> list[dict]:
        coin, quote = symbol.upper(), market.upper()
        payload = self._query("DIGITAL_CURRENCY_DAILY", symbol=coin, market=quote)
        series = payload.get("Time Series (Digital Currency Daily)")
        if not isinstance(series, dict):
            raise AlphaVantageError("Alpha Vantage crypto daily time series is missing")
        rows = []
        for date, values in series.items():
            if not isinstance(values, dict):
                continue
            row = {"symbol": f"{coin}{quote}", "asset_class": "crypto", "date": date}
            for field, prefixes in (
                ("open", ("1a. open", "1b. open")),
                ("high", ("2a. high", "2b. high")),
                ("low", ("3a. low", "3b. low")),
                ("close", ("4a. close", "4b. close")),
            ):
                raw = next((v for k, v in values.items() if k.startswith(prefixes)), None)
                try:
                    row[field] = float(raw)
                except (TypeError, ValueError) as exc:
                    raise AlphaVantageError("Alpha Vantage crypto OHLC field is missing or invalid") from exc
            row.update({"source": "alpha_vantage", "interval": "1day"})
            rows.append(row)
        if not rows:
            raise AlphaVantageError("Alpha Vantage returned no crypto daily observations")
        return sorted(rows, key=lambda row: row["date"], reverse=True)
