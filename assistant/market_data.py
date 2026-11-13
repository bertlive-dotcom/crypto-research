"""Provider-neutral market observations and fail-closed quality checks."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping


def parse_aware_timestamp(value: Any) -> datetime:
    """Parse ISO-8601 and require an explicit timezone offset."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be valid ISO-8601") from exc
    else:
        raise ValueError("timestamp must be an ISO-8601 string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def validate_quote(
    quote: Mapping[str, Any], *, max_age_seconds: int,
    now: datetime | None = None, future_tolerance_seconds: int = 30,
) -> dict:
    """Validate a quote; return reasons instead of silently coercing bad data."""
    if max_age_seconds < 0 or future_tolerance_seconds < 0:
        raise ValueError("age limits must be non-negative")
    reasons: list[str] = []
    required = ("symbol", "asset_class", "price", "currency", "source", "observed_at")
    for field in required:
        if quote.get(field) in (None, ""):
            reasons.append(f"missing_{field}")

    price = None
    try:
        price = float(quote.get("price"))
        if not math.isfinite(price) or price <= 0:
            reasons.append("invalid_price")
    except (TypeError, ValueError, OverflowError):
        reasons.append("invalid_price")

    age_seconds = None
    if quote.get("observed_at") not in (None, ""):
        try:
            observed = parse_aware_timestamp(quote["observed_at"])
            current = parse_aware_timestamp(now or datetime.now(timezone.utc))
            age_seconds = (current - observed).total_seconds()
            if age_seconds < -future_tolerance_seconds:
                reasons.append("future_market_data")
            elif age_seconds > max_age_seconds:
                reasons.append("stale_market_data")
        except (TypeError, ValueError, OverflowError):
            reasons.append("invalid_observed_at")

    return {
        "usable": not reasons,
        "reasons": reasons,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "price": price if price is not None and math.isfinite(price) and price > 0 else None,
    }


def validate_closed_candle(
    candle: Mapping[str, Any], *, now: datetime | None = None,
    max_age_seconds: int,
) -> dict:
    """Validate OHLC integrity, timezone and closure/freshness of a candle."""
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    reasons: list[str] = []
    values: dict[str, float] = {}
    for field in ("open", "high", "low", "close"):
        try:
            value = float(candle.get(field))
            if not math.isfinite(value) or value <= 0:
                raise ValueError
            values[field] = value
        except (TypeError, ValueError, OverflowError):
            reasons.append(f"invalid_{field}")

    if len(values) == 4:
        if values["high"] < max(values.values()) or values["low"] > min(values.values()):
            reasons.append("inconsistent_ohlc")

    age_seconds = None
    try:
        close_time = parse_aware_timestamp(candle.get("close_timestamp"))
        current = parse_aware_timestamp(now or datetime.now(timezone.utc))
        age_seconds = (current - close_time).total_seconds()
        if age_seconds < 0:
            reasons.append("candle_not_closed")
        elif age_seconds > max_age_seconds:
            reasons.append("stale_candle")
    except (TypeError, ValueError, OverflowError):
        reasons.append("invalid_close_timestamp")

    for field in ("symbol", "asset_class", "source", "interval"):
        if candle.get(field) in (None, ""):
            reasons.append(f"missing_{field}")

    return {
        "usable": not reasons,
        "reasons": reasons,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "ohlc": values if len(values) == 4 else None,
    }
