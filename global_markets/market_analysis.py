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
    """Exclude still-forming candles, reject future data, then calculate indicators."""
    candles = sorted(list(rows), key=lambda row: row.get("timestamp", ""))
    if not candles:
        return {"eligible": False, "status": "missing", "reasons": ["no_candles"]}
    symbol = candles[-1].get("symbol")
    interval = candles[-1].get("interval")
    current = _dt(now or datetime.now(timezone.utc))
    reasons = []
    if interval not in MAX_AGE_SECONDS:
        reasons.append("unsupported_interval")
    if any(row.get("symbol") != symbol or row.get("interval") != interval for row in candles):
        reasons.append("mixed_symbol_or_interval")
    try:
        closed_candles = []
        for row in candles:
            opened_at = _dt(row["timestamp"])
            closed_at = _dt(row["close_timestamp"])
            if opened_at > current and (opened_at - current).total_seconds() > 300:
                reasons.append("future_candle")
                continue
            # Binance includes the currently forming candle. It must not enter
            # technical calculations until its close time has passed.
            if closed_at > current:
                continue
            closed_candles.append(row)
        if not closed_candles:
            reasons.append("no_closed_candles")
            return {"eligible": False, "status": "rejected", "symbol": symbol,
                    "interval": interval, "bars": 0, "reasons": reasons}
        closes = [float(row["close"]) for row in closed_candles]
        if any(value <= 0 for value in closes):
            reasons.append("invalid_close_price")
        timestamps = [_dt(row["close_timestamp"]) for row in closed_candles]
        latest_age = (current - timestamps[-1]).total_seconds()
        allowed_age = max_age_seconds if max_age_seconds is not None else MAX_AGE_SECONDS.get(interval, 0)
        if latest_age > allowed_age:
            reasons.append("stale_market_data")
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"eligible": False, "status": "invalid", "symbol": symbol,
                "interval": interval, "reasons": ["malformed_candle_data"]}
    if len(closed_candles) < MIN_BARS:
        reasons.append("insufficient_history")
    if reasons:
        return {"eligible": False, "status": "rejected", "symbol": symbol,
                "interval": interval, "bars": len(closed_candles),
                "age_seconds": round(latest_age, 1),
                "reasons": sorted(set(reasons))}

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
    return_7d = ((closes[-1] / closes[-8]) - 1) * 100 if interval == "1d" and len(closes) >= 8 else None
    return_30d = ((closes[-1] / closes[-31]) - 1) * 100 if interval == "1d" and len(closes) >= 31 else None
    score_parts = [
        25 if closes[-1] > sma20 else 0,
        25 if sma50 is not None and sma20 > sma50 else 12.5 if sma50 is None else 0,
        25 if macd > macd_signal else 0,
        25 if rsi is not None and 50 <= rsi <= 70 else 12.5 if rsi is not None and 40 <= rsi < 50 else 0,
    ]
    return {
        "eligible": True, "status": "fresh", "symbol": symbol, "interval": interval,
        "source": closed_candles[-1].get("source"), "bars": len(closed_candles),
        "latest_close": closes[-1], "latest_candle_close": timestamps[-1].isoformat(),
        "age_seconds": round(latest_age, 1),
        "indicators": {
            "rsi_14": rsi, "macd_12_26": round(macd, 8),
            "macd_signal_9": round(macd_signal, 8) if macd_signal is not None else None,
            "sma_20": round(sma20, 8), "sma_50": round(sma50, 8) if sma50 is not None else None,
            "realized_volatility_pct_annualized_approx": round(volatility, 2) if volatility is not None else None,
            "return_7d_pct": round(return_7d, 2) if return_7d is not None else None,
            "return_30d_pct": round(return_30d, 2) if return_30d is not None else None,
        },
        "technical_screen_score": sum(score_parts),
        "score_type": "technical_only_not_investment_recommendation", "reasons": [],
    }



def classify_timeframe_structure(daily: dict | None, tactical: dict | None) -> dict:
    """Classify multi-timeframe structure using score, RSI and MACD confirmation."""
    if not daily or not tactical or not daily.get("eligible") or not tactical.get("eligible"):
        return {"category": "insufficient_timeframes", "label": "Intervals insuficients",
                "explanation": "Calen dades diàries i 4h recents i tancades."}
    d_score, t_score = daily["technical_screen_score"], tactical["technical_screen_score"]
    d_ind, t_ind = daily["indicators"], tactical["indicators"]
    t_macd_bullish = (t_ind.get("macd_12_26") is not None
                      and t_ind.get("macd_signal_9") is not None
                      and t_ind["macd_12_26"] > t_ind["macd_signal_9"])
    d_macd_bullish = (d_ind.get("macd_12_26") is not None
                      and d_ind.get("macd_signal_9") is not None
                      and d_ind["macd_12_26"] > d_ind["macd_signal_9"])
    t_rsi_confirmed = t_ind.get("rsi_14") is not None and t_ind["rsi_14"] >= 50
    d_rsi_confirmed = d_ind.get("rsi_14") is not None and d_ind["rsi_14"] >= 50
    if (d_score >= 62.5 and t_score >= 62.5 and d_rsi_confirmed
            and t_rsi_confirmed and d_macd_bullish and t_macd_bullish):
        return {"category": "confirmed_trend", "label": "Tendència confirmada",
                "explanation": "Tots dos intervals tenen puntuació forta, RSI >= 50 i MACD alcista."}
    if d_score <= 37.5 and t_score >= 62.5:
        if t_rsi_confirmed and t_macd_bullish:
            return {"category": "possible_reversal", "label": "Possible gir (pendent del diari)",
                    "explanation": "El 4h confirma RSI i MACD alcistes, però la tendència diària continua feble."}
        return {"category": "incipient_recovery", "label": "Recuperació incipient",
                "explanation": "El 4h millora, però encara no hi ha confirmació conjunta d'RSI i MACD."}
    if d_score >= 62.5 and t_score <= 50:
        return {"category": "timeframe_divergence", "label": "Divergència temporal",
                "explanation": "La força diària no està confirmada en 4h."}
    if d_score <= 37.5 and t_score <= 37.5:
        return {"category": "weakness", "label": "Feblesa",
                "explanation": "Tots dos intervals mostren debilitat tècnica."}
    return {"category": "mixed_structure", "label": "Estructura mixta",
            "explanation": "Els indicadors no coincideixen prou per classificar una tendència o recuperació."}


def analyze_feed(feed_result: dict, *, now: datetime | None = None) -> dict:
    """Analyze each returned symbol/interval group and preserve feed failures."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in feed_result.get("data", []):
        grouped.setdefault((row.get("symbol"), row.get("interval")), []).append(row)
    analyses = [analyze_candles(group, now=now) for _, group in sorted(grouped.items())]
    eligible = [item for item in analyses if item["eligible"]]
    rejected = [item for item in analyses if not item["eligible"]]

    # Cross-timeframe alignment is calculated only when both closed, fresh
    # intervals exist for the same provider symbol. Daily trend has more weight.
    by_symbol: dict[str, dict[str, dict]] = {}
    for item in eligible:
        by_symbol.setdefault(item["symbol"], {})[item["interval"]] = item
    cross_timeframe = []
    btc_daily = by_symbol.get("BTCUSDT", {}).get("1d")
    btc_indicators = btc_daily.get("indicators", {}) if btc_daily else {}
    for symbol, frames in sorted(by_symbol.items()):
        daily, tactical = frames.get("1d"), frames.get("4h")
        if not daily or not tactical:
            continue
        combined = round(
            daily["technical_screen_score"] * 0.60
            + tactical["technical_screen_score"] * 0.40, 1
        )
        if combined >= 70:
            stance = "bullish_alignment"
        elif combined <= 30:
            stance = "bearish_alignment"
        else:
            stance = "mixed_or_neutral"
        structure = classify_timeframe_structure(daily, tactical)
        daily_indicators = daily["indicators"]
        btc_7d = btc_indicators.get("return_7d_pct")
        btc_30d = btc_indicators.get("return_30d_pct")
        asset_7d = daily_indicators.get("return_7d_pct")
        asset_30d = daily_indicators.get("return_30d_pct")
        cross_timeframe.append({
            "symbol": symbol,
            "daily_score": daily["technical_screen_score"],
            "4h_score": tactical["technical_screen_score"],
            "alignment_score": combined,
            "stance": stance,
            "structure": structure["category"],
            "structure_label": structure["label"],
            "structure_explanation": structure["explanation"],
            "return_7d_pct": asset_7d,
            "return_30d_pct": asset_30d,
            "relative_strength_vs_btc_7d_pct": round(asset_7d - btc_7d, 2) if asset_7d is not None and btc_7d is not None else None,
            "relative_strength_vs_btc_30d_pct": round(asset_30d - btc_30d, 2) if asset_30d is not None and btc_30d is not None else None,
            "daily_price": daily["latest_close"],
            "4h_price": tactical["latest_close"],
        })
    cross_timeframe.sort(key=lambda row: row["alignment_score"], reverse=True)
    return {
        "source": feed_result.get("source"), "observed_at": feed_result.get("observed_at"),
        "read_only": True, "analyses": analyses,
        "eligible_series": len(eligible), "rejected_series": len(rejected),
        "cross_timeframe": cross_timeframe,
        "provider_unavailable": feed_result.get("unavailable", []),
    }
