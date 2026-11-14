"""Canonical market-candle normalization and fail-closed quality checks."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _number(row: dict[str, Any], field: str, *, optional: bool = False) -> float | None:
    value = row.get(field)
    if value is None and optional:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def normalize_candle(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    max_future_skew_seconds: float = 5.0,
) -> dict[str, Any]:
    """Normalize one provider candle without inventing missing market fields.

    A still-forming candle is retained with is_closed=False; downstream
    indicators and scanner decisions must explicitly exclude it.
    """
    if not isinstance(row, dict):
        raise ValueError("candle must be an object")

    symbol = row.get("symbol")
    provider = row.get("source") or row.get("provider")
    interval = row.get("interval")
    asset_class = row.get("asset_class")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol is required")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("source/provider is required")
    if not isinstance(interval, str) or not interval.strip():
        raise ValueError("interval is required")
    if not isinstance(asset_class, str) or not asset_class.strip():
        raise ValueError("asset_class is required")

    opened = _parse_timestamp(row.get("timestamp"), "timestamp")
    closed = _parse_timestamp(row.get("close_timestamp"), "close_timestamp")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if opened > current and (opened - current).total_seconds() > max_future_skew_seconds:
        raise ValueError("candle timestamp is in the future")
    if closed < opened:
        raise ValueError("close_timestamp precedes timestamp")

    values = {field: _number(row, field) for field in ("open", "high", "low", "close")}
    if any(value is None or value <= 0 for value in values.values()):
        raise ValueError("OHLC values must be positive")
    if values["high"] < max(values["open"], values["low"], values["close"]):
        raise ValueError("high is inconsistent with OHLC")
    if values["low"] > min(values["open"], values["high"], values["close"]):
        raise ValueError("low is inconsistent with OHLC")

    volume = _number(row, "volume", optional=True)
    if volume is not None and volume < 0:
        raise ValueError("volume cannot be negative")

    return {
        "symbol": symbol.strip().upper(),
        "provider_symbol": str(row.get("provider_symbol") or symbol).strip(),
        "source": provider.strip().lower(),
        "asset_class": asset_class.strip().lower(),
        "interval": interval.strip().lower(),
        "timestamp": opened.isoformat(),
        "close_timestamp": closed.isoformat(),
        **values,
        "volume": volume,
        "volume_available": volume is not None,
        "currency": row.get("currency"),
        "exchange": row.get("exchange"),
        "is_closed": closed <= current,
        "ingested_at": current.isoformat(),
    }
