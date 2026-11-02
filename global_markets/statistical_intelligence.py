"""Descriptive, event-based crypto pattern research.

This module is deliberately separate from the live scanner and paper ledger.
It uses only closed OHLC candles and reports historical conditional outcomes;
it does not predict prices or create trade signals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import median
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
            "median_forward_return_pct": round(median(values), 3) if count else None,
            "positive_outcome_pct": round(sum(value > 0 for value in values) / count * 100, 1) if count else None,
            "sample_status": "usable_for_exploration" if count >= min_sample else "small_sample",
        }
    return result


def _market_regimes(candles: list[dict]) -> list[str | None]:
    """Classify each candle using only information available at that close.

    Bullish/bearish regimes require price relative to its 50-day SMA and the
    SMA direction versus 10 candles earlier. Earlier history is left unclassified.
    """
    closes = [candle["close"] for candle in candles]
    regimes: list[str | None] = [None] * len(candles)
    for index in range(59, len(candles)):
        sma_now = sum(closes[index - 49:index + 1]) / 50
        sma_previous = sum(closes[index - 59:index - 9]) / 50
        price = closes[index]
        if price > sma_now and sma_now > sma_previous:
            regimes[index] = "bullish"
        elif price < sma_now and sma_now < sma_previous:
            regimes[index] = "bearish"
        else:
            regimes[index] = "sideways_or_transition"
    return regimes



def _volatility_regimes(candles: list[dict], *, window: int = 20,
                        reference_window: int = 180) -> list[str | None]:
    """Classify realized volatility against a trailing historical median."""
    from math import log, sqrt
    closes = [candle["close"] for candle in candles]
    returns: list[float | None] = [None]
    for index in range(1, len(closes)):
        returns.append(log(closes[index] / closes[index - 1]))
    rolling: list[float | None] = [None] * len(candles)
    for index in range(window, len(candles)):
        values = returns[index - window + 1:index + 1]
        if len(values) == window:
            mean = sum(values) / window
            variance = sum((value - mean) ** 2 for value in values) / (window - 1)
            rolling[index] = sqrt(variance) * sqrt(365) * 100
    labels: list[str | None] = [None] * len(candles)
    for index, current in enumerate(rolling):
        history = [v for v in rolling[max(0, index-reference_window):index] if v is not None]
        if current is not None and len(history) == reference_window:
            labels[index] = "high_volatility" if current > median(history) else "low_volatility"
    return labels

def _combined_regimes(candles: list[dict]) -> list[str | None]:
    """Combine trend and volatility labels; unavailable inputs stay unclassified."""
    trends = _market_regimes(candles)
    volatility = _volatility_regimes(candles)
    return [
        f"{trend}_{vol}" if trend is not None and vol is not None else None
        for trend, vol in zip(trends, volatility)
    ]


def _regime_comparison(candles: list[dict], events: dict[str, list[dict]],
                       horizons: tuple[int, ...], min_sample: int,
                       regime_labels: list[str | None] | None = None,
                       expected_regimes: tuple[str, ...] | None = None) -> dict:
    """Compare each pattern with unconditional returns in the same regime."""
    regimes = regime_labels if regime_labels is not None else _market_regimes(candles)
    result: dict[str, dict] = {}
    for pattern, occurrences in events.items():
        by_regime: dict[str, list[dict]] = {}
        for event in occurrences:
            index = event["index"]
            regime = regimes[index]
            if regime is None:
                continue
            direction = event["direction"]
            entry = candles[index]["close"]
            outcomes = {}
            baselines = {}
            for horizon in horizons:
                target = index + horizon
                if target < len(candles):
                    raw = (candles[target]["close"] / entry - 1) * 100
                    outcomes[str(horizon)] = raw * direction if direction else raw
                else:
                    outcomes[str(horizon)] = None
            by_regime.setdefault(regime, []).append({"outcomes": outcomes})
        regimes_to_report = expected_regimes or (
            ("high_volatility", "low_volatility") if regime_labels is not None else
            ("bullish", "bearish", "sideways_or_transition")
        )
        for regime in regimes_to_report:
            by_regime.setdefault(regime, [])
        result[pattern] = {}
        for regime, observations in by_regime.items():
            metrics = {}
            for horizon in horizons:
                key = str(horizon)
                event_values = [o["outcomes"][key] for o in observations if o["outcomes"][key] is not None]
                # Matched baseline: every eligible candle in this regime, with the
                # same directional convention as the pattern being evaluated.
                baseline_values = []
                direction = 0
                pattern_events = [e for e in occurrences if regimes[e["index"]] == regime]
                if pattern_events:
                    direction = pattern_events[0]["direction"]
                for index, candle_regime in enumerate(regimes):
                    target = index + int(horizon)
                    if candle_regime == regime and target < len(candles):
                        raw = (candles[target]["close"] / candles[index]["close"] - 1) * 100
                        baseline_values.append(raw * direction if direction else raw)
                n = len(event_values)
                event_mean = sum(event_values) / n if n else None
                baseline_mean = sum(baseline_values) / len(baseline_values) if baseline_values else None
                metrics[key] = {
                    "observations": n,
                    "event_mean_return_pct": round(event_mean, 3) if event_mean is not None else None,
                    "matched_baseline_mean_return_pct": round(baseline_mean, 3) if baseline_mean is not None else None,
                    "excess_vs_baseline_pct_points": round(event_mean - baseline_mean, 3) if event_mean is not None and baseline_mean is not None else None,
                    "sample_status": "usable_for_exploration" if n >= min_sample else "small_sample",
                }
            result[pattern][regime] = metrics
    return result


def _chronological_validation(
    candles: list[dict], events: dict[str, list[dict]],
    horizons: tuple[int, ...], min_sample: int,
) -> dict:
    """Evaluate the later 30% of history separately from the earlier 70%."""
    split_index = int(len(candles) * 0.70)
    trend = _market_regimes(candles)
    volatility = _volatility_regimes(candles)
    combined = _combined_regimes(candles)
    split_date = candles[split_index]["_close_time"].date().isoformat() if candles else None
    result: dict[str, Any] = {
        "method": "chronological_holdout",
        "exploration_fraction": 0.70,
        "holdout_fraction": 0.30,
        "holdout_start_date": split_date,
        "holdout_candles": max(0, len(candles) - split_index),
        "patterns": {},
        "limitations": [
            "Single chronological holdout; results remain exploratory and may be regime-dependent.",
            "Holdout events are counted only when the full forward horizon remains inside available history.",
            "This is not a formal significance test and does not correct for multiple pattern/horizon comparisons.",
        ],
    }
    regime_names = (
        "bullish_high_volatility", "bullish_low_volatility",
        "bearish_high_volatility", "bearish_low_volatility",
        "sideways_or_transition_high_volatility",
        "sideways_or_transition_low_volatility",
    )
    for pattern, occurrences in events.items():
        pattern_result: dict[str, Any] = {}
        for regime in regime_names:
            pattern_events = [
                event for event in occurrences
                if event["index"] >= split_index
                and combined[event["index"]] == regime
            ]
            cell: dict[str, Any] = {}
            for horizon in horizons:
                eligible = [
                    event for event in pattern_events
                    if event["index"] + horizon < len(candles)
                ]
                event_returns = []
                for event in eligible:
                    index = event["index"]
                    raw = (candles[index + horizon]["close"] / candles[index]["close"] - 1) * 100
                    event_returns.append(raw * event["direction"] if event["direction"] else raw)
                baseline_returns = []
                direction = pattern_events[0]["direction"] if pattern_events else 0
                for index in range(split_index, len(candles) - horizon):
                    if combined[index] == regime:
                        raw = (candles[index + horizon]["close"] / candles[index]["close"] - 1) * 100
                        baseline_returns.append(raw * direction if direction else raw)
                n = len(event_returns)
                event_mean = sum(event_returns) / n if n else None
                baseline_mean = sum(baseline_returns) / len(baseline_returns) if baseline_returns else None
                cell[str(horizon)] = {
                    "observations": n,
                    "event_mean_return_pct": round(event_mean, 3) if event_mean is not None else None,
                    "matched_baseline_observations": len(baseline_returns),
                    "matched_baseline_mean_return_pct": round(baseline_mean, 3) if baseline_mean is not None else None,
                    "excess_vs_baseline_pct_points": round(event_mean - baseline_mean, 3)
                    if event_mean is not None and baseline_mean is not None else None,
                    "sample_status": "usable_for_exploration" if n >= min_sample else "small_sample",
                }
            pattern_result[regime] = cell
        result["patterns"][pattern] = pattern_result
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
    trend_labels = _market_regimes(candles)
    volatility_labels = _volatility_regimes(candles)
    combined_labels = _combined_regimes(candles)
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
                "trend_regime": trend_labels[index],
                "volatility_regime": volatility_labels[index],
                "combined_regime": combined_labels[index],
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
        "regime_analysis": _regime_comparison(candles, events, horizons, min_sample),
        "volatility_regime_analysis": _regime_comparison(
            candles, events, horizons, min_sample, regime_labels=_volatility_regimes(candles)
        ),
        "combined_regime_analysis": _regime_comparison(
            candles, events, horizons, min_sample,
            regime_labels=combined_labels,
            expected_regimes=(
                "bullish_high_volatility", "bullish_low_volatility",
                "bearish_high_volatility", "bearish_low_volatility",
                "sideways_or_transition_high_volatility",
                "sideways_or_transition_low_volatility",
            ),
        ),
        "chronological_validation": _chronological_validation(
            candles, events, horizons, min_sample
        ),
        "limitations": [
            "Descriptive historical statistics, not predictive probabilities.",
            "Close-to-close outcomes do not model executable entries, fees, slippage, stops or take-profits.",
            "Overlapping pattern events are retained and are not statistically independent.",
            "Daily candles do not capture intraday session behaviour.",
            "Small samples must not be used as an entry filter.",
            "Volatility labels require 20 daily returns and 180 prior volatility observations; earlier candles remain unclassified.",
            "High/low volatility is relative to the trailing historical median, not an absolute threshold.",
            "Combined trend/volatility cells require both regime labels; early warm-up candles are excluded.",
        ],
    }
