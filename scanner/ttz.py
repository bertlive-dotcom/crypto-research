"""TTZ-inspired, research-only price-action features.

This module does not issue trade instructions and is deliberately isolated from
paper-entry eligibility. It uses only fully closed OHLCV candles supplied by
the caller. Signals are heuristic labels, not probabilities or forecasts.
"""
from __future__ import annotations

from typing import Any


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def analyze_price_action(
    candles: list[dict[str, Any]],
    lookback: int = 20,
    retest_tolerance_pct: float = 0.003,
) -> dict[str, Any]:
    """Return wick, failed-breakout, retest and exhaustion diagnostics.

    Candle dictionaries require open/high/low/close/volume. The caller must
    exclude the currently forming candle before calling this function.
    """
    if lookback < 2:
        raise ValueError("lookback must be at least 2")
    if not 0 <= retest_tolerance_pct <= 0.02:
        raise ValueError("retest_tolerance_pct must be between 0 and 0.02")

    normalized: list[dict[str, float]] = []
    for row in candles:
        try:
            o, h, l, c, v = (
                float(row["open"]), float(row["high"]), float(row["low"]),
                float(row["close"]), float(row["volume"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or h < l:
            continue
        normalized.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

    empty = {
        "status": "INSUFFICIENT_DATA",
        "lookback": lookback,
        "range_high": None,
        "range_low": None,
        "wick_rejection": "NONE",
        "failed_breakout": "NONE",
        "retest": "NONE",
        "exhaustion": "NONE",
        "volume_ratio": None,
    }
    if len(normalized) < lookback + 2:
        return empty

    current = normalized[-1]
    previous = normalized[-2]
    prior_range = normalized[-lookback-1:-1]
    range_high = max(row["high"] for row in prior_range)
    range_low = min(row["low"] for row in prior_range)

    candle_range = current["high"] - current["low"]
    if candle_range <= 0:
        upper_wick = lower_wick = close_position = 0.0
    else:
        upper_wick = current["high"] - max(current["open"], current["close"])
        lower_wick = min(current["open"], current["close"]) - current["low"]
        close_position = (current["close"] - current["low"]) / candle_range

    wick_rejection = "NONE"
    if upper_wick / max(candle_range, 1e-12) >= 0.45 and close_position <= 0.55:
        wick_rejection = "BEARISH"
    elif lower_wick / max(candle_range, 1e-12) >= 0.45 and close_position >= 0.45:
        wick_rejection = "BULLISH"

    failed_breakout = "NONE"
    if current["high"] > range_high and current["close"] <= range_high:
        failed_breakout = "FAILED_HIGH"
    elif current["low"] < range_low and current["close"] >= range_low:
        failed_breakout = "FAILED_LOW"

    # A retest requires a prior candle to close outside its then-known range,
    # followed by the current candle revisiting that level and closing beyond it.
    prior_reference = normalized[-lookback-2:-2]
    retest = "NONE"
    if len(prior_reference) == lookback:
        breakout_high = max(row["high"] for row in prior_reference)
        breakout_low = min(row["low"] for row in prior_reference)
        tolerance_high = breakout_high * retest_tolerance_pct
        tolerance_low = breakout_low * retest_tolerance_pct
        if previous["close"] > breakout_high:
            touched = current["low"] <= breakout_high + tolerance_high
            if touched and current["close"] > breakout_high:
                retest = "BULLISH"
        elif previous["close"] < breakout_low:
            touched = current["high"] >= breakout_low - tolerance_low
            if touched and current["close"] < breakout_low:
                retest = "BEARISH"

    baseline = sum(row["volume"] for row in normalized[-21:-1]) / 20
    volume_ratio = current["volume"] / baseline if baseline > 0 else None
    exhaustion = "NONE"
    high_volume = volume_ratio is not None and volume_ratio >= 1.5
    if high_volume and wick_rejection == "BEARISH":
        exhaustion = "UPSIDE"
    elif high_volume and wick_rejection == "BULLISH":
        exhaustion = "DOWNSIDE"

    return {
        "status": "READY",
        "lookback": lookback,
        "range_high": range_high,
        "range_low": range_low,
        "wick_rejection": wick_rejection,
        "failed_breakout": failed_breakout,
        "retest": retest,
        "exhaustion": exhaustion,
        "volume_ratio": volume_ratio,
    }
