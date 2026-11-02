"""Read-only intraday context statistics for closed Binance Spot candles.

Groups hourly forward returns by UTC hour, weekday and trailing trend/volatility
regimes. Descriptive only: no signals, orders or connection to trading logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, log, sqrt
from statistics import median


HORIZONS = (1, 3, 6, 12)


def _parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def closed_hourly_candles(rows, now=None):
    """Validate OHLC and keep only fully closed, chronologically ordered rows."""
    current = _parse_time(now or datetime.now(timezone.utc))
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close_time = _parse_time(row.get("close_timestamp"))
        timestamp = _parse_time(row.get("timestamp"))
        if close_time is None or timestamp is None or close_time > current:
            continue
        try:
            o, h, low, c = (float(row[key]) for key in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(isfinite(v) and v > 0 for v in (o, h, low, c)):
            continue
        if low > min(o, c) or h < max(o, c) or low > h:
            continue
        item = dict(row)
        item.update(open=o, high=h, low=low, close=c, _time=timestamp, _close_time=close_time)
        valid.append(item)
    valid.sort(key=lambda x: x["_time"])
    # Avoid duplicate timestamps contaminating hourly bucket counts.
    deduped = {}
    for item in valid:
        deduped[item["_time"]] = item
    return list(deduped.values())


def _sma(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i-period+1:i+1]) / period
    return out


def _regimes(candles, vol_window=20, vol_reference=180):
    closes = [c["close"] for c in candles]
    sma50 = _sma(closes, 50)
    trend = [None] * len(candles)
    for i in range(59, len(candles)):
        prior = sum(closes[i-59:i-9]) / 50
        if closes[i] > sma50[i] and sma50[i] > prior:
            trend[i] = "bullish"
        elif closes[i] < sma50[i] and sma50[i] < prior:
            trend[i] = "bearish"
        else:
            trend[i] = "sideways_or_transition"

    log_returns = [None] + [log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
    realized = [None] * len(candles)
    for i in range(vol_window, len(candles)):
        values = log_returns[i-vol_window+1:i+1]
        mean = sum(values) / len(values)
        variance = sum((v-mean)**2 for v in values) / (len(values)-1)
        realized[i] = sqrt(variance) * sqrt(24*365) * 100
    volatility = [None] * len(candles)
    for i, value in enumerate(realized):
        history = [v for v in realized[max(0, i-vol_reference):i] if v is not None]
        if value is not None and len(history) == vol_reference:
            volatility[i] = "high_volatility" if value > median(history) else "low_volatility"
    combined = [
        f"{t}_{v}" if t and v else None
        for t, v in zip(trend, volatility)
    ]
    return trend, volatility, combined


def _metric(values, baseline):
    n = len(values)
    return {
        "observations": n,
        "mean_forward_return_pct": round(sum(values)/n, 4) if n else None,
        "median_forward_return_pct": round(median(values), 4) if n else None,
        "positive_outcome_pct": round(sum(v > 0 for v in values)/n*100, 2) if n else None,
        "matched_baseline_mean_pct": round(sum(baseline)/len(baseline), 4) if baseline else None,
        "excess_vs_baseline_pct_points": round(sum(values)/n-sum(baseline)/len(baseline), 4)
            if n and baseline else None,
        "sample_status": "usable_for_exploration" if n >= 30 else "small_sample",
    }


def analyze_context(rows, symbol=None, now=None, horizons=HORIZONS, min_sample=30):
    if not horizons or any(not isinstance(h, int) or h < 1 for h in horizons):
        raise ValueError("horizons must be positive integers")
    if min_sample < 1:
        raise ValueError("min_sample must be positive")
    candles = closed_hourly_candles(rows, now=now)
    if not candles:
        raise ValueError("no valid closed hourly candles")
    trend, volatility, combined = _regimes(candles)
    split = int(len(candles) * 0.70)
    dimensions = {
        "utc_hour": lambda i: f"{candles[i]['_time'].hour:02d}:00",
        "utc_weekday": lambda i: candles[i]["_time"].strftime("%A"),
        "trend_regime": lambda i: trend[i],
        "volatility_regime": lambda i: volatility[i],
        "combined_regime": lambda i: combined[i],
    }
    report = {
        "symbol": (symbol or candles[-1].get("symbol") or "UNKNOWN").upper(),
        "source": "Binance Spot",
        "interval": "1h",
        "closed_candles": len(candles),
        "first_candle_utc": candles[0]["_time"].isoformat(),
        "last_candle_utc": candles[-1]["_time"].isoformat(),
        "exploration_fraction": 0.70,
        "holdout_fraction": 0.30,
        "holdout_start_utc": candles[split]["_time"].isoformat() if split < len(candles) else None,
        "horizons_hours": list(horizons),
        "minimum_sample": min_sample,
        "dimensions": {},
        "limitations": [
            "Descriptive research only; no trade signals or execution connection.",
            "UTC hour and weekday buckets are not exchange-session labels or local time.",
            "The 70/30 split is chronological; holdout groups may have small samples.",
            "Forward returns overlap, so observations are not independent.",
            "Trend uses trailing SMA50 and its direction versus 10 hours earlier.",
            "Volatility is annualized rolling 20-hour realized volatility versus the median of 180 prior observations.",
            "No fees, spread, slippage, funding, fills or market impact are modeled.",
            "The 1,000-candle public endpoint limit gives roughly 41 days of hourly history; longer history needs paginated retrieval.",
        ],
    }
    for dimension, label_fn in dimensions.items():
        buckets = {}
        for i in range(len(candles)):
            label = label_fn(i)
            if label is not None:
                buckets.setdefault(label, []).append(i)
        dimension_result = {}
        for label, indices in sorted(buckets.items()):
            bucket_result = {}
            for horizon in horizons:
                eligible = [i for i in indices if i + horizon < len(candles)]
                all_explore = [i for i in range(0, split) if i + horizon < split]
                all_holdout = [i for i in range(split, len(candles)) if i + horizon < len(candles)]
                def vals(items):
                    return [
                        (candles[i+horizon]["close"]/candles[i]["close"]-1)*100
                        for i in items
                    ]
                bucket_result[str(horizon)] = {
                    "all": _metric(vals(eligible), vals(range(0, len(candles)-horizon))),
                    "exploration": _metric(vals([i for i in eligible if i < split and i+horizon < split]), vals(all_explore)),
                    "holdout": _metric(vals([i for i in eligible if i >= split]), vals(all_holdout)),
                }
            dimension_result[label] = dimension_result if False else bucket_result
        report["dimensions"][dimension] = dimension_result
    return report
