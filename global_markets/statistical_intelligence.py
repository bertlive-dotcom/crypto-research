"""Descriptive, event-based crypto pattern research.

This module is deliberately separate from the live scanner and paper ledger.
It uses only closed OHLC candles and reports historical conditional outcomes;
it does not predict prices or create trade signals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable


DEFAULT_HORIZONS = (1, 3, 5)
DEFAULT_MIN_SAMPLE = 30


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def closed_candles(rows: Iterable[dict], *, now: datetime | None = None) -> list[dict]:
    """Validate basic OHLC values and exclude candles that have not closed."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close_time = _timestamp(row.get("close_timestamp"))
        if close_time is None or close_time > current:
            continue
        try:
            o, h, low, c = (float(row[key]) for key in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(isfinite(value) and value > 0 for value in (o, h, low, c)):
            continue
        if low > min(o, c) or h < max(o, c) or low > h:
            continue
        item = dict(row)
        item.update({"open": o, "high": h, "low": low, "close": c})
        item["_close_time"] = close_time
        valid.append(item)
    valid.sort(key=lambda item: item["_close_time"])
    return valid


def _summarize(events: list[dict], horizons: tuple[int, ...], min_sample: int) -> dict:
    result = {"occurrences": len(events), "horizons": {}}
    for horizon in horizons:
        outcomes = [event["forward_returns_pct"].get(str(horizon)) for event in events]
        values = [value for value in outcomes if value is not None and isfinite(value)]
        count = len(values)
        result["horizons"][str(horizon)] = {
            "observations": count,
            "mean_forward_return_pct": round(sum(values) / count, 3) if count else None,
            "median_forward_return_pct": round(sorted(values)[count // 2], 3) if count else None,
            "positive_outcome_pct": round(sum(value > 0 for value in values) / count * 100, 1) if count else None,
            "sample_status": "usable_for_exploration" if count >= min_sample else "small_sample",
        }
    return result


def analyze_pattern_history(
    rows: Iterable[dict],
    *,
    symbol: str | None = None,
    now: datetime | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict:
    """Measure inside-bar, engulfing and prior-range breakout outcomes.

    Returns are close-to-close, direction-adjusted, and measured from the
    pattern candle close. No fees, slippage, entry execution or stop logic are
    modeled. Overlapping events are retained and therefore are not independent.
    """
    if not horizons or any(not isinstance(h, int) or h < 1 for h in horizons):
        raise ValueError("horizons must contain positive integer candle counts")
    if min_sample < 1:
        raise ValueError("min_sample must be positive")

    candles = closed_candles(rows, now=now)
    asset = (symbol or (candles[-1].get("symbol") if candles else "UNKNOWN")).upper()
    events: dict[str, list[dict]] = {
        "inside_bar": [], "bullish_engulfing": [], "bearish_engulfing": [],
        "prior_day_range_breakout_up": [], "prior_day_range_breakout_down": [],
    }

    for index in range(1, len(candles)):
        previous, current = candles[index - 1], candles[index]
        if current["high"] < previous["high"] and current["low"] > previous["low"]:
            events["inside_bar"].append({"index": index, "direction": 0})
        prev_body_low, prev_body_high = sorted((previous["open"], previous["close"]))
        body_low, body_high = sorted((current["open"], current["close"]))
        if (current["close"] > current["open"] and previous["close"] < previous["open"]
                and body_low <= prev_body_low and body_high >= prev_body_high):
            events["bullish_engulfing"].append({"index": index, "direction": 1})
        if (current["close"] < current["open"] and previous["close"] > previous["open"]
                and body_low <= prev_body_low and body_high >= prev_body_high):
            events["bearish_engulfing"].append({"index": index, "direction": -1})
        if current["close"] > previous["high"]:
            events["prior_day_range_breakout_up"].append({"index": index, "direction": 1})
        if current["close"] < previous["low"]:
            events["prior_day_range_breakout_down"].append({"index": index, "direction": -1})

    details = {}
    for pattern, occurrences in events.items():
        enriched = []
        for event in occurrences:
            index, direction = event["index"], event["direction"]
            entry_close = candles[index]["close"]
            forward = {}
            for horizon in horizons:
                target_index = index + horizon
                if target_index < len(candles):
                    raw_return = (candles[target_index]["close"] / entry_close - 1) * 100
                    forward[str(horizon)] = round(raw_return * direction, 4) if direction else round(raw_return, 4)
                else:
                    forward[str(horizon)] = None
            enriched.append({
                "date": candles[index].get("date") or candles[index]["_close_time"].date().isoformat(),
                "direction": "long" if direction > 0 else "short" if direction < 0 else "not_directional",
                "forward_returns_pct": forward,
            })
        details[pattern] = {
            **_summarize(enriched, horizons, min_sample),
            "direction_adjustment": "long_short_signed" if pattern != "inside_bar" else "unsigned_close_return",
            "events": enriched,
        }

    return {
        "symbol": asset,
        "source": "Binance Spot daily OHLC",
        "interval": "1d",
        "closed_candles": len(candles),
        "first_candle": candles[0]["date"] if candles else None,
        "last_candle": candles[-1]["date"] if candles else None,
        "minimum_sample": min_sample,
        "horizons_candles": list(horizons),
        "patterns": details,
        "limitations": [
            "Descriptive historical statistics, not predictive probabilities.",
            "Close-to-close outcomes do not model executable entries, fees, slippage, stops or take-profits.",
            "Overlapping pattern events are retained and are not statistically independent.",
            "Daily candles do not capture intraday session behaviour.",
            "Small samples must not be used as an entry filter.",
        ],
    }
