"""Freshness validation and technical indicators for normalized crypto candles.

No fundamental/catalyst score is inferred here. The technical score is a
screening metric only and must not be presented as a complete opportunity rank.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from statistics import pstdev
from typing import Iterable


MAX_AGE_SECONDS = {"4h": 8 * 3600, "1d": 36 * 3600}
MIN_BARS = 35


def _dt(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    alpha = 2 / (period + 1)
    current = seed
    for index in range(period, len(values)):
        current = values[index] * alpha + current * (1 - alpha)
        result[index] = current
    return result


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def analyze_candles(rows: Iterable[dict], *, now: datetime | None = None,
                    max_age_seconds: int | None = None) -> dict:
    """Validate one symbol/interval series and compute indicators if eligible."""
    candles = sorted(list(rows), key=lambda row: row.get("timestamp", ""))
    if not candles:
        return {"eligible": False, "status": "missing", "reasons": ["no_candles"]}
    symbol = candles[-1].get("symbol")
    interval = candles[-1].get("interval")
    reasons = []
    if interval not in MAX_AGE_SECONDS:
        reasons.append("unsupported_interval")
    if any(row.get("symbol") != symbol or row.get("interval") != interval for row in candles):
        reasons.append("mixed_symbol_or_interval")
    try:
        closes = [float(row["close"]) for row in candles]
        if any(value <= 0 for value in closes):
            reasons.append("invalid_close_price")
        timestamps = [_dt(row["close_timestamp"]) for row in candles]
        current = _dt(now or datetime.now(timezone.utc))
        latest_age = (current - timestamps[-1]).total_seconds()
        if latest_age < -300:
            reasons.append("future_candle")
        allowed_age = max_age_seconds if max_age_seconds is not None else MAX_AGE_SECONDS.get(interval, 0)
        if latest_age > allowed_age:
            reasons.append("stale_market_data")
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"eligible": False, "status": "invalid", "symbol": symbol,
                "interval": interval, "reasons": ["malformed_candle_data"]}
    if len(candles) < MIN_BARS:
        reasons.append("insufficient_history")
    if reasons:
        return {"eligible": False, "status": "rejected", "symbol": symbol,
                "interval": interval, "bars": len(candles), "age_seconds": round(latest_age, 1),
                "reasons": reasons}

    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    macd_series = [a - b for a, b in zip(ema12, ema26) if a is not None and b is not None]
    signal_series = _ema(macd_series, 9)
    macd = macd_series[-1]
    macd_signal = signal_series[-1]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    rsi = _rsi(closes)
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
    volatility = pstdev(returns[-20:]) * sqrt(6) * 100 if len(returns) >= 20 and interval == "4h" else (
        pstdev(returns[-20:]) * sqrt(365) * 100 if len(returns) >= 20 else None
    )
    score_parts = [
        25 if closes[-1] > sma20 else 0,
        25 if sma50 is not None and sma20 > sma50 else 12.5 if sma50 is None else 0,
        25 if macd > macd_signal else 0,
        25 if rsi is not None and 50 <= rsi <= 70 else 12.5 if rsi is not None and 40 <= rsi < 50 else 0,
    ]
    return {
        "eligible": True,
        "status": "fresh",
        "symbol": symbol,
        "interval": interval,
        "source": candles[-1].get("source"),
        "bars": len(candles),
        "latest_close": closes[-1],
        "latest_candle_close": timestamps[-1].isoformat(),
        "age_seconds": round(latest_age, 1),
        "indicators": {
            "rsi_14": rsi,
            "macd_12_26": round(macd, 8),
            "macd_signal_9": round(macd_signal, 8) if macd_signal is not None else None,
            "sma_20": round(sma20, 8),
            "sma_50": round(sma50, 8) if sma50 is not None else None,
            "realized_volatility_pct_annualized_approx": round(volatility, 2) if volatility is not None else None,
        },
        "technical_screen_score": sum(score_parts),
        "score_type": "technical_only_not_investment_recommendation",
        "reasons": [],
    }


def analyze_feed(feed_result: dict, *, now: datetime | None = None) -> dict:
    """Analyze each returned symbol/interval group and preserve feed failures."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in feed_result.get("data", []):
        grouped.setdefault((row.get("symbol"), row.get("interval")), []).append(row)
    analyses = [
        analyze_candles(group, now=now)
        for _, group in sorted(grouped.items())
    ]
    eligible = [item for item in analyses if item["eligible"]]
    rejected = [item for item in analyses if not item["eligible"]]
    return {
        "source": feed_result.get("source"),
        "observed_at": feed_result.get("observed_at"),
        "read_only": True,
        "analyses": analyses,
        "eligible_series": len(eligible),
        "rejected_series": len(rejected),
        "provider_unavailable": feed_result.get("unavailable", []),
    }
