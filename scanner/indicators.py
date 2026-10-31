"""Small dependency-free indicator helpers for closed Binance candles."""
from __future__ import annotations
import math

def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result

def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains, losses = [], []
    for previous, current in zip(values[:-1], values[1:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

def macd_histogram(values: list[float]) -> float | None:
    fast, slow = ema(values, 12), ema(values, 26)
    if not fast or not slow:
        return None
    # EMA arrays have different starting offsets; align their final 9 values.
    offset = 26 - 12
    aligned_fast = fast[offset:]
    macd = [a - b for a, b in zip(aligned_fast, slow)]
    signal = ema(macd, 9)
    if not signal:
        return None
    return macd[-1] - signal[-1]

def atr_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    true_ranges = []
    for i in range(1, len(closes)):
        true_ranges.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return (atr / closes[-1]) * 100.0 if closes[-1] else None

def candle_series(raw: list[list]) -> dict:
    # Ignore the currently forming candle to prevent look-ahead/intrabar flicker.
    rows = raw[:-1]
    return {
        "open_time": [int(x[0]) for x in rows],
        "high": [float(x[2]) for x in rows],
        "low": [float(x[3]) for x in rows],
        "close": [float(x[4]) for x in rows],
        "volume": [float(x[5]) for x in rows],
    }

def volume_ratio(volumes: list[float], period: int = 20) -> float | None:
    if len(volumes) < period + 1:
        return None
    baseline = sum(volumes[-period-1:-1]) / period
    return volumes[-1] / baseline if baseline > 0 else None
