"""Research-only diagnostics derived from the six trading-course lessons.

Pure functions over caller-supplied OHLCV candles. Not imported by the live/paper
scanner and never changes eligibility, sizing, entries or exits.
"""
from __future__ import annotations

from statistics import mean


def ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return [None] * len(values)
    out: list[float | None] = [None] * (period - 1)
    current = sum(values[:period]) / period
    out.append(current)
    alpha = 2.0 / (period + 1)
    for value in values[period:]:
        current = alpha * value + (1 - alpha) * current
        out.append(current)
    return out


def stochastic(candles: list[dict], period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    if min(period, smooth_k, smooth_d) <= 0:
        raise ValueError("stochastic periods must be positive")
    raw = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        lo = min(float(x["low"]) for x in candles[i-period+1:i+1])
        hi = max(float(x["high"]) for x in candles[i-period+1:i+1])
        raw[i] = 50.0 if hi == lo else 100 * (float(candles[i]["close"]) - lo) / (hi - lo)
    k = [None] * len(candles)
    for i in range(len(candles)):
        vals = [x for x in raw[max(0, i-smooth_k+1):i+1] if x is not None]
        if len(vals) == smooth_k:
            k[i] = mean(vals)
    d = [None] * len(candles)
    for i in range(len(candles)):
        vals = [x for x in k[max(0, i-smooth_d+1):i+1] if x is not None]
        if len(vals) == smooth_d:
            d[i] = mean(vals)
    return {"k": k, "d": d, "raw_k": raw}


def adx(candles: list[dict], period: int = 14):
    """Wilder ADX and directional indicators; ADX is strength, not direction."""
    n = len(candles)
    if period <= 0:
        raise ValueError("period must be positive")
    plus_di = [None] * n
    minus_di = [None] * n
    adx_values = [None] * n
    if n <= period * 2:
        return {"adx": adx_values, "plus_di": plus_di, "minus_di": minus_di}
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        high, low = float(candles[i]["high"]), float(candles[i]["low"])
        prev_high, prev_low = float(candles[i-1]["high"]), float(candles[i-1]["low"])
        prev_close = float(candles[i-1]["close"])
        up, down = high - prev_high, prev_low - low
        tr.append(max(high-low, abs(high-prev_close), abs(low-prev_close)))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    smooth_tr = sum(tr[:period])
    smooth_plus = sum(plus_dm[:period])
    smooth_minus = sum(minus_dm[:period])
    dx = [None] * n
    for i in range(period, len(tr) + 1):
        if i > period:
            smooth_tr = smooth_tr - smooth_tr / period + tr[i-1]
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i-1]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i-1]
        candle_index = i
        if smooth_tr <= 0:
            continue
        pdi = 100 * smooth_plus / smooth_tr
        mdi = 100 * smooth_minus / smooth_tr
        plus_di[candle_index], minus_di[candle_index] = pdi, mdi
        denom = pdi + mdi
        dx[candle_index] = 100 * abs(pdi-mdi) / denom if denom else 0.0
    seed = [x for x in dx[period:period*2] if x is not None]
    if len(seed) < period:
        return {"adx": adx_values, "plus_di": plus_di, "minus_di": minus_di}
    current = mean(seed)
    adx_values[period*2] = current
    for i in range(period*2 + 1, n):
        if dx[i] is not None:
            current = ((current * (period - 1)) + dx[i]) / period
            adx_values[i] = current
    return {"adx": adx_values, "plus_di": plus_di, "minus_di": minus_di}


def confirmed_pivots(candles: list[dict], left: int = 3, right: int = 3):
    """Pivots become available only at pivot_index + right; no future leak."""
    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    highs, lows = [], []
    for i in range(left, len(candles) - right):
        hi = float(candles[i]["high"])
        lo = float(candles[i]["low"])
        window = candles[i-left:i+right+1]
        if hi == max(float(x["high"]) for x in window) and sum(float(x["high"]) == hi for x in window) == 1:
            highs.append({"kind": "high", "pivot_index": i, "confirmed_at_index": i+right, "price": hi})
        if lo == min(float(x["low"]) for x in window) and sum(float(x["low"]) == lo for x in window) == 1:
            lows.append({"kind": "low", "pivot_index": i, "confirmed_at_index": i+right, "price": lo})
    return {"highs": highs, "lows": lows}


def fvg_zones(candles: list[dict]):
    """Three-candle imbalance: bullish low[i] > high[i-2], bearish high[i] < low[i-2]."""
    zones = []
    for i in range(2, len(candles)):
        a, c = candles[i-2], candles[i]
        a_high, a_low = float(a["high"]), float(a["low"])
        c_high, c_low = float(c["high"]), float(c["low"])
        if c_low > a_high:
            zones.append({"direction": "bullish", "lower": a_high, "upper": c_low,
                          "formed_at_index": i, "known_at_index": i})
        elif c_high < a_low:
            zones.append({"direction": "bearish", "lower": c_high, "upper": a_low,
                          "formed_at_index": i, "known_at_index": i})
    return zones


def wick_profile(candle: dict):
    op, hi, lo, close = (float(candle[k]) for k in ("open", "high", "low", "close"))
    span = hi - lo
    if span <= 0 or hi < max(op, close) or lo > min(op, close):
        raise ValueError("invalid OHLC candle")
    body = abs(close - op)
    upper = hi - max(op, close)
    lower = min(op, close) - lo
    return {
        "body_pct_range": body / span * 100,
        "upper_wick_pct_range": upper / span * 100,
        "lower_wick_pct_range": lower / span * 100,
        "close_location_pct": (close - lo) / span * 100,
        "upper_rejection_candidate": upper >= max(body * 2, span * .4) and close < lo + span * .6,
        "lower_rejection_candidate": lower >= max(body * 2, span * .4) and close > lo + span * .4,
    }


def weekly_trend(weekly_candles: list[dict], period: int = 50):
    closes = [float(x["close"]) for x in weekly_candles]
    values = ema(closes, period)
    if not values or values[-1] is None:
        return {"status": "insufficient_history", "ema": None, "slope": None, "direction": "unknown"}
    prior = values[-2] if len(values) >= 2 else None
    last = values[-1]
    price = closes[-1]
    direction = "bullish" if price > last and prior is not None and last > prior else (
        "bearish" if price < last and prior is not None and last < prior else "neutral")
    return {"status": "available", "ema": last,
            "slope_pct": ((last / prior) - 1) * 100 if prior else None,
            "direction": direction, "last_close": price}


def course_diagnostics(weekly: list[dict], daily: list[dict], four_hour: list[dict]):
    """Return an explainable read-only snapshot; never an entry/exit instruction."""
    if not daily or not four_hour:
        raise ValueError("daily and four-hour candles are required")
    dclose = [float(x["close"]) for x in daily]
    d50, d200 = ema(dclose, 50), ema(dclose, 200)
    stoch = stochastic(four_hour)
    strength = adx(four_hour)
    pivots = confirmed_pivots(daily)
    zones = fvg_zones(four_hour)
    latest = four_hour[-1]
    wick = wick_profile(latest)
    return {
        "status": "diagnostic_only",
        "weekly_ema50": weekly_trend(weekly, 50) if weekly else {"status": "missing_weekly_data"},
        "daily_trend": {
            "ema50": d50[-1], "ema200": d200[-1],
            "direction": "bullish" if d50[-1] is not None and d200[-1] is not None and dclose[-1] > d50[-1] > d200[-1]
                         else "bearish" if d50[-1] is not None and d200[-1] is not None and dclose[-1] < d50[-1] < d200[-1]
                         else "neutral_or_insufficient",
        },
        "four_hour_momentum": {
            "stochastic_14_3_3_k": stoch["k"][-1],
            "stochastic_14_3_3_d": stoch["d"][-1],
            "adx14": strength["adx"][-1],
            "plus_di14": strength["plus_di"][-1],
            "minus_di14": strength["minus_di"][-1],
        },
        "confirmed_daily_pivots": {
            "latest_high": next((x for x in reversed(pivots["highs"]) if x["confirmed_at_index"] < len(daily)), None),
            "latest_low": next((x for x in reversed(pivots["lows"]) if x["confirmed_at_index"] < len(daily)), None),
        },
        "four_hour_fvg": zones[-10:],
        "latest_four_hour_wick": wick,
        "squeeze_momentum": {
            "status": "not_implemented",
            "reason": "Exact course indicator/script has not been verified; no substitute formula is assumed.",
        },
        "execution_notice": "Diagnostics only. Do not use as a trading signal or change scanner eligibility.",
    }
