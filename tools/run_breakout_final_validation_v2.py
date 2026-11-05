"""Final robustness validation: matched breakout/retest with equal and ATR stops.

Read-only Binance Spot research. This module does not import or modify any trading
scanner, paper ledger, order execution, portfolio or production configuration.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError
from global_markets.statistical_intelligence import closed_candles, _ema, _rsi, _atr, _sma

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT",
    "DOGEUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "BCHUSDT",
    "DOTUSDT", "TONUSDT", "UNIUSDT", "NEARUSDT", "ETCUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "SUIUSDT", "AAVEUSDT", "ATOMUSDT", "FILUSDT",
    "INJUSDT", "ICPUSDT", "XLMUSDT", "HBARUSDT", "ZECUSDT", "PEPEUSDT",
    "WIFUSDT", "BONKUSDT", "RENDERUSDT", "FETUSDT", "TAOUSDT", "SEIUSDT",
]
WINDOWS = (2, 3, 5)
COSTS = (0.30, 0.50, 0.75)
STOP_MODES = ("equal_distance_1_5_atr", "atr_at_entry_1_5")
BLOCK_DAYS = 5


def _trend_regime(close, index):
    if index < 59:
        return None
    now = sum(close[index - 49:index + 1]) / 50
    prior = sum(close[index - 59:index - 9]) / 50
    if close[index] > now and now > prior:
        return "bullish"
    if close[index] < now and now < prior:
        return "bearish"
    return "sideways"


def _volatility_regime(candles, atr, index):
    if index < 200 or atr[index] is None:
        return None
    current = atr[index] / float(candles[index]["close"])
    history = [
        atr[j] / float(candles[j]["close"])
        for j in range(max(14, index - 180), index)
        if atr[j] is not None and float(candles[j]["close"]) > 0
    ]
    if len(history) < 150:
        return None
    threshold = sorted(history)[len(history) // 2]
    return "high_vol" if current > threshold else "low_vol"


def _regime(candles, close, atr, index):
    trend = _trend_regime(close, index)
    vol = _volatility_regime(candles, atr, index)
    return f"{trend}_{vol}" if trend and vol else "unclassified"


def _simulate(candles, entry_index, side, distance, cost=0.30, rr=2.0, max_hold=5):
    if entry_index >= len(candles) or distance <= 0:
        return None
    entry = float(candles[entry_index]["open"])
    stop = entry - side * distance
    target = entry + side * distance * rr
    if entry <= 0 or (side == 1 and stop <= 0):
        return None
    end = min(len(candles), entry_index + max_hold)
    exit_price, exit_index, reason = float(candles[end - 1]["close"]), end - 1, "time_exit"
    for j in range(entry_index, end):
        bar = candles[j]
        op, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
        if (side == 1 and op <= stop) or (side == -1 and op >= stop):
            exit_price, exit_index, reason = op, j, "stop_gap"
            break
        stop_hit = lo <= stop if side == 1 else hi >= stop
        target_hit = hi >= target if side == 1 else lo <= target
        if stop_hit:
            exit_price, exit_index, reason = stop, j, "stop_loss"
            break
        if target_hit:
            exit_price, exit_index, reason = target, j, "take_profit"
            break
    gross = (exit_price / entry - 1) * 100 * side
    risk_pct = distance / entry * 100
    return {
        "entry_timestamp": candles[entry_index].get("timestamp"),
        "exit_timestamp": candles[exit_index].get("timestamp"),
        "entry_index": entry_index, "exit_index": exit_index,
        "gross_return_pct": gross, "net_return_pct": gross - cost,
        "risk_pct": risk_pct, "net_r": (gross - cost) / risk_pct,
        "exit_reason": reason, "bars_held": exit_index - entry_index + 1,
    }


def _signals(candles):
    n = len(candles)
    close = [float(x["close"]) for x in candles]
    high = [float(x["high"]) for x in candles]
    low = [float(x["low"]) for x in candles]
    opn = [float(x["open"]) for x in candles]
    volume = [float(x.get("volume", 0) or 0) for x in candles]
    e50, e200 = _ema(close, 50), _ema(close, 200)
    e12, e26 = _ema(close, 12), _ema(close, 26)
    macd = [e12[i] - e26[i] if e12[i] is not None and e26[i] is not None else None for i in range(n)]
    signal = _ema([x if x is not None else 0.0 for x in macd], 9)
    rsi, atr, vavg = _rsi(close), _atr(candles), _sma(volume, 20)
    events = []
    for i in range(200, n - 8):
        vals = (e50[i], e200[i], rsi[i], atr[i], vavg[i], macd[i], signal[i])
        if any(v is None for v in vals) or atr[i] <= 0 or not vavg[i]:
            continue
        vol_ok = volume[i] >= vavg[i] * 1.20
        side = 1 if (
            close[i] > high[i - 1] and close[i] > e50[i] > e200[i]
            and 50 <= rsi[i] <= 70 and macd[i] > signal[i] and vol_ok
        ) else -1 if (
            close[i] < low[i - 1] and close[i] < e50[i] < e200[i]
            and 30 <= rsi[i] <= 50 and macd[i] < signal[i] and vol_ok
        ) else 0
        if side:
            events.append({
                "index": i, "side": side, "level": high[i - 1] if side == 1 else low[i - 1],
                "atr": atr[i], "regime": _regime(candles, close, atr, i),
                "timestamp": candles[i].get("timestamp"),
            })
    return events, close, high, low, opn, atr


def _find_retest(candles, event, window, high, low, opn):
    i, side, level = event["index"], event["side"], event["level"]
    tolerance = event["atr"] * 0.25
    for j in range(i + 1, min(i + window, len(candles) - 2) + 1):
        close = float(candles[j]["close"])
        if side == 1:
            invalid, touched, rejected = close < level - tolerance, low[j] <= level + tolerance, close > level and close > opn[j]
        else:
            invalid, touched, rejected = close > level + tolerance, high[j] >= level - tolerance, close < level and close < opn[j]
        if invalid:
            return None
        if touched and rejected:
            return j
    return None


FREEZE_DATE = "2026-11-03"


def _split(index, n, historical_count):
    """Use pre-freeze history for exploration/validation; later candles are prospective."""
    if index >= historical_count:
        return "prospective_forward_holdout", n
    exploration_end = int(historical_count * .70)
    return ("exploration", exploration_end) if index < exploration_end else ("validation", historical_count)


def build_asset(candles, window):
    events, close, high, low, opn, atr = _signals(candles)
    output = {mode: {"pairs": [], "direct_all": []} for mode in STOP_MODES}
    historical_count = sum(1 for candle in candles if str(candle.get("date", "")) <= FREEZE_DATE)
    for event in events:
        i, side = event["index"], event["side"]
        split, boundary = _split(i, len(candles), historical_count)
        retest_index = _find_retest(candles, event, window, high, low, opn)
        for mode in STOP_MODES:
            direct_entry = i + 1
            if direct_entry >= boundary:
                continue
            # Both legs use the same absolute stop distance for the equal-distance test.
            # ATR-at-entry uses the ATR known at each entry signal's close.
            direct_distance = 1.5 * event["atr"]
            direct = _simulate(candles, direct_entry, side, direct_distance)
            if direct is None or direct["exit_index"] >= boundary:
                continue
            output[mode]["direct_all"].append({
                "split": split, "timestamp": event["timestamp"], "side": side,
                "regime": event["regime"], "trade": direct,
            })
            if retest_index is None or retest_index + 1 >= boundary:
                continue
            retest_entry = retest_index + 1
            if mode == "equal_distance_1_5_atr":
                retest_distance = direct_distance
            else:
                # ATR is calculated using the retest candle close, before next-open entry.
                retest_distance = 1.5 * atr[retest_index]
            retest = _simulate(candles, retest_entry, side, retest_distance)
            if retest is None or retest["exit_index"] >= boundary:
                continue
            output[mode]["pairs"].append({
                "split": split, "timestamp": event["timestamp"], "side": side,
                "regime": event["regime"], "direct": direct, "retest": retest,
                "delta_r": retest["net_r"] - direct["net_r"],
            })
    return output


def _metrics(trades):
    if not trades:
        return {"n": 0, "win_rate_pct": None, "mean_net_pct": None,
                "mean_net_r": None, "profit_factor": None,
                "max_drawdown_r": None, "max_losing_streak": None}
    ordered = sorted(trades, key=lambda t: t["entry_timestamp"])
    returns = [t["net_return_pct"] for t in ordered]
    rs = [t["net_r"] for t in ordered]
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    equity, peak, max_dd = 0.0, 0.0, 0.0
    streak = max_streak = 0
    for value in rs:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)
    return {
        "n": len(ordered), "win_rate_pct": round(len(wins) / len(ordered) * 100, 2),
        "mean_net_pct": round(mean(returns), 4), "mean_net_r": round(mean(rs), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r_trade_sequence": round(max_dd, 4),
        "max_losing_streak": max_streak,
    }


def _date_key(timestamp):
    return str(timestamp)[:10] if timestamp else "unknown"


def _date_cluster_bootstrap(pairs, iterations=5000, block=5, seed=42):
    by_date = {}
    for pair in pairs:
        by_date.setdefault(_date_key(pair["timestamp"]), []).append(pair["delta_r"])
    dates = sorted(by_date)
    if len(dates) < 20:
        return {"date_clusters": len(dates), "status": "insufficient_date_clusters",
                "ci95_low": None, "ci95_high": None, "prob_delta_positive": None}
    daily = [mean(by_date[d]) for d in dates]
    rng = random.Random(seed)
    n = len(daily)
    block_count = (n + block - 1) // block
    draws = []
    for _ in range(iterations):
        sample = []
        for _ in range(block_count):
            start = rng.randrange(n)
            sample.extend(daily[(start + k) % n] for k in range(block))
        draws.append(mean(sample[:n]))
    draws.sort()
    return {
        "date_clusters": n, "block_dates": block, "iterations": iterations,
        "ci95_low": round(draws[int(iterations * .025)], 5),
        "ci95_high": round(draws[min(iterations - 1, int(iterations * .975))], 5),
        "prob_delta_positive": round(sum(x > 0 for x in draws) / iterations, 4),
        "status": "descriptive_cross_asset_date_cluster_bootstrap",
    }


def _regime_summary(rows):
    result = {}
    labels = ("long", "short", "bullish_high_vol", "bullish_low_vol",
              "bearish_high_vol", "bearish_low_vol", "sideways_high_vol",
              "sideways_low_vol", "unclassified")
    for label in labels:
        group = rows if label == "all" else [
            x for x in rows
            if (("long" if x["side"] == 1 else "short") if label in ("long", "short") else x["regime"]) == label
        ]
        if label == "all" or group:
            result[label] = {
                "direct": _metrics([x["direct"] for x in group]) if group and "direct" in group[0] else None,
                "retest": _metrics([x["retest"] for x in group]) if group and "retest" in group[0] else None,
                "mean_delta_r": round(mean([x["delta_r"] for x in group]), 5) if group and "delta_r" in group[0] else None,
                "n": len(group),
            }
    return result


def _summarize_mode(asset_data, mode):
    all_pairs = [p for a in asset_data for p in a[mode]["pairs"]]
    all_direct = [p for a in asset_data for p in a[mode]["direct_all"]]
    result = {}
    for split in ("exploration", "validation", "prospective_forward_holdout"):
        pairs = [p for p in all_pairs if p["split"] == split]
        direct_all = [p for p in all_direct if p["split"] == split]
        paired_direct = [p["direct"] for p in pairs]
        retest = [p["retest"] for p in pairs]
        delta = [p["delta_r"] for p in pairs]
        result[split] = {
            "all_breakout_direct_benchmark": _metrics([p["trade"] for p in direct_all]),
            "paired_direct": _metrics(paired_direct),
            "paired_retest": _metrics(retest),
            "paired_delta_mean_r": round(mean(delta), 5) if delta else None,
            "date_cluster_bootstrap": _date_cluster_bootstrap(pairs) if split == "prospective_forward_holdout" else None,
            "interpretation_status": (
                "insufficient_prospective_sample"
                if split == "prospective_forward_holdout" and (
                    len(pairs) < 60 or len({_date_key(p['timestamp']) for p in pairs}) < 30
                ) else "descriptive_only"
            ),
            "subgroups": _regime_summary([
                {**p, "direct": p["direct"], "retest": p["retest"],
                 "side": p["side"], "regime": p["regime"]} for p in pairs
            ]),
        }
    return result


def run(limit, symbols):
    client = BinanceMarketDataClient()
    candles_by_asset, unavailable = {}, []
    for symbol in symbols:
        try:
            candles = closed_candles(client.get_klines_history(symbol, interval="1d", total_limit=limit))
            if len(candles) < 500:
                unavailable.append({"symbol": symbol, "reason": f"only {len(candles)} closed candles"})
            else:
                candles_by_asset[symbol] = candles
        except (BinanceMarketDataError, ValueError) as exc:
            unavailable.append({"symbol": symbol, "reason": str(exc)})
    # Select a single window using only exploration and the equal-distance stop test.
    per_window = {}
    cached = {}
    for window in WINDOWS:
        rows = []
        for symbol, candles in candles_by_asset.items():
            built = build_asset(candles, window)
            cached[(symbol, window)] = built
            rows.extend(p for p in built["equal_distance_1_5_atr"]["pairs"] if p["split"] == "exploration")
        per_window[window] = {
            "n": len(rows),
            "mean_delta_r": mean([p["delta_r"] for p in rows]) if rows else None,
        }
    eligible = [(v["mean_delta_r"], w) for w, v in per_window.items() if v["n"] >= 30]
    selected = max(eligible)[1] if eligible else None
    report_modes = {}
    for mode in STOP_MODES:
        report_modes[mode] = _summarize_mode(
            [cached[(symbol, selected)] for symbol in candles_by_asset] if selected else [], mode
        )
    return {
        "report_type": "breakout_final_validation_v2",
        "methodology": {
            "universe": symbols, "timeframe": "1d", "requested_history": limit,
            "available_assets": len(candles_by_asset), "unavailable": unavailable,
            "partition": "Historical candles through 2026-11-03 are split 70% exploration / 30% validation. The final holdout is strictly prospective: only candles after 2026-11-03. Entry and exit must remain inside their partition.",
        "freeze_date": FREEZE_DATE,
        "historical_holdout_status": "The previously inspected historical final segment is not reused as a fresh holdout. A new forward period is reserved after the frozen date.",
        "prospective_minimum": "Do not interpret the forward holdout until at least 60 paired events across at least 30 distinct dates; otherwise report insufficient prospective sample.",
            "frozen_window": selected, "window_selection": "selected only on pooled exploration mean paired delta under equal-distance 1.5 ATR stop; same frozen window applied to both stop models",
            "stop_tests": {
                "equal_distance_1_5_atr": "Both entries use the same absolute stop distance: 1.5 x ATR known at breakout close. This isolates entry timing while preserving same 2R target and 5-bar holding limit.",
                "atr_at_entry_1_5": "Each strategy uses 1.5 x ATR known at its own entry signal close, before next-open execution; target 2R and max hold 5 bars.",
            },
            "costs": "0.30% round trip base; report uses the same base cost for both; prior cost sensitivity was 0.30/0.50/0.75%.",
            "regimes": "Independent trend regime from price vs SMA50 and SMA50 slope over 10 bars, combined with high/low ATR-to-price volatility vs trailing 180-day median.",
            "risk_metrics": "Trade-sequence drawdown in R and maximum losing streak are descriptive, not a capital-weighted portfolio simulation; overlapping cross-asset positions are not netted.",
            "bootstrap": "5-day moving blocks over calendar-date clusters, with all asset events on each date grouped together; 5000 resamples; descriptive interval only.",
            "benchmark": "Unconditional direct breakout includes all eligible signals regardless of later retest occurrence; paired sample is reported separately.",
            "limitations": "OHLC intrabar order is unknown; stop-first convention is conservative. Bootstrap is descriptive and does not eliminate all cross-asset dependence or model-selection risk.",
        },
        "window_exploration_only": {str(k): v for k, v in per_window.items()},
        "results_by_stop_model": report_modes,
        "safety": "Read-only Binance Spot public data; no credentials, orders, scanner, paper ledger, open positions or production settings accessed.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10000, choices=(3000, 5000, 7500, 10000))
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--output", default="reports/breakout_final_validation_v2.json")
    args = parser.parse_args()
    result = run(args.limit, args.symbols)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved final validation for {result['methodology']['available_assets']} assets: {path}")
    return 0 if result["methodology"]["available_assets"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
