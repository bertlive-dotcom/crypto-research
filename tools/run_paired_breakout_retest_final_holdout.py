"""Paired breakout-vs-retest study with a frozen final chronological holdout.

Read-only Binance Spot research. No trading-system imports or execution integrations.
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

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT",
    "DOGEUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "BCHUSDT",
    "DOTUSDT", "TONUSDT", "UNIUSDT", "NEARUSDT", "ETCUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "SUIUSDT", "AAVEUSDT", "ATOMUSDT", "FILUSDT",
    "INJUSDT", "ICPUSDT", "XLMUSDT", "HBARUSDT", "ZECUSDT", "PEPEUSDT",
    "WIFUSDT", "BONKUSDT", "RENDERUSDT", "FETUSDT", "TAOUSDT", "SEIUSDT",
]
WINDOWS = (2, 3, 5)
COSTS = (0.30, 0.50, 0.75)
BLOCK_LENGTH = 5


def _regime(close, e50, e200, i):
    if e50[i] is None or e200[i] is None:
        return "unclassified"
    if close[i] > e50[i] > e200[i]:
        return "bullish"
    if close[i] < e50[i] < e200[i]:
        return "bearish"
    return "sideways_or_transition"


def _simulate(candles, entry_i, side, stop, atr_value, max_hold=5, rr=2.0, cost=0.30):
    if entry_i >= len(candles):
        return None
    entry = float(candles[entry_i]["open"])
    risk = abs(entry - stop)
    if risk <= 0 or (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        return None
    target = entry + side * risk * rr
    last = min(entry_i + max_hold - 1, len(candles) - 1)
    exit_price, exit_i, reason = float(candles[last]["close"]), last, "time_exit"
    for k in range(entry_i, last + 1):
        b = candles[k]
        op, hi, lo = float(b["open"]), float(b["high"]), float(b["low"])
        if (side == 1 and op <= stop) or (side == -1 and op >= stop):
            exit_price, exit_i, reason = op, k, "stop_gap"
            break
        stop_hit = lo <= stop if side == 1 else hi >= stop
        target_hit = hi >= target if side == 1 else lo <= target
        if stop_hit:  # conservative when both barriers touch in one OHLC candle
            exit_price, exit_i, reason = stop, k, "stop_loss"
            break
        if target_hit:
            exit_price, exit_i, reason = target, k, "take_profit"
            break
    gross_pct = (exit_price / entry - 1.0) * 100.0 * side
    net_pct = gross_pct - cost
    return {
        "entry_timestamp": candles[entry_i].get("timestamp"),
        "exit_timestamp": candles[exit_i].get("timestamp"),
        "entry": entry, "stop": stop, "target": target, "exit": exit_price,
        "exit_reason": reason, "gross_return_pct": gross_pct,
        "net_return_pct": net_pct, "risk_pct": risk / entry * 100.0,
        "net_r": net_pct / (risk / entry * 100.0),
        "bars_held": exit_i - entry_i + 1,
    }


def build_pairs(candles, retest_window):
    """Create event-matched direct and retest trades with the same exit policy."""
    n = len(candles)
    close = [float(c["close"]) for c in candles]
    high = [float(c["high"]) for c in candles]
    low = [float(c["low"]) for c in candles]
    opn = [float(c["open"]) for c in candles]
    volume = [float(c.get("volume", 0) or 0) for c in candles]
    e50, e200 = _ema(close, 50), _ema(close, 200)
    e12, e26 = _ema(close, 12), _ema(close, 26)
    macd = [e12[i] - e26[i] if e12[i] is not None and e26[i] is not None else None for i in range(n)]
    signal = _ema([x if x is not None else 0.0 for x in macd], 9)
    rsi, atr, vavg = _rsi(close), _atr(candles), _sma(volume, 20)
    pairs, unmatched, direct_all = [], [], []
    # Partition boundaries are candle-index based; trades are purged if either leg exits
    # beyond the partition's end, preventing outcome leakage across split boundaries.
    cut1, cut2 = int(n * 0.60), int(n * 0.80)
    split_bounds = {
        "exploration": (0, cut1),
        "validation": (cut1, cut2),
        "final_holdout": (cut2, n),
    }
    for i in range(200, n - 7):
        vals = (e50[i], e200[i], rsi[i], atr[i], vavg[i], macd[i], signal[i])
        if any(v is None for v in vals) or atr[i] <= 0 or not vavg[i]:
            continue
        vol_ok = volume[i] >= vavg[i] * 1.20
        side = 1 if (close[i] > high[i-1] and close[i] > e50[i] > e200[i]
                     and 50 <= rsi[i] <= 70 and macd[i] > signal[i] and vol_ok) else (
               -1 if (close[i] < low[i-1] and close[i] < e50[i] < e200[i]
                     and 30 <= rsi[i] <= 50 and macd[i] < signal[i] and vol_ok) else 0)
        if not side:
            continue
        level = high[i-1] if side == 1 else low[i-1]
        # Direct entry: next candle open. Stop anchored to breakout candle.
        direct_stop = min(low[i], level - atr[i] * 0.5) if side == 1 else max(high[i], level + atr[i] * 0.5)
        direct = _simulate(candles, i + 1, side, direct_stop, atr[i], cost=0.30)
        if direct is None:
            continue
        split = "exploration" if i < cut1 else ("validation" if i < cut2 else "final_holdout")
        split_end = split_bounds[split][1]
        # Keep each strategy's trade entirely inside its assigned chronological partition.
        if i + 1 >= split_end or (direct.get("exit_timestamp") is not None
                                  and int(direct["exit_timestamp"]) >= int(candles[split_end - 1]["timestamp"])):
            continue
        direct_all.append({
            "event_id": f"{candles[i].get('timestamp')}:{side}",
            "breakout_timestamp": candles[i].get("timestamp"),
            "side": "long" if side == 1 else "short",
            "regime": _regime(close, e50, e200, i),
            "split": split, "direct": direct,
        })
        found = None
        for j in range(i + 1, min(i + retest_window, n - 2) + 1):
            tol = atr[i] * 0.25
            if side == 1:
                invalid = close[j] < level - tol
                touched = low[j] <= level + tol
                rejected = close[j] > level and close[j] > opn[j]
            else:
                invalid = close[j] > level + tol
                touched = high[j] >= level - tol
                rejected = close[j] < level and close[j] < opn[j]
            if invalid:
                break
            if touched and rejected:
                found = j
                break
        if found is None:
            unmatched.append({"breakout_index": i, "side": "long" if side == 1 else "short",
                              "timestamp": candles[i].get("timestamp")})
            continue
        # Same 2R target, 5-bar maximum holding period, cost, gap/stop-first rules.
        # Retest stop uses the retest candle extreme and the same 0.5 ATR level buffer.
        retest_stop = min(low[found], level - atr[found] * 0.5) if side == 1 else max(high[found], level + atr[found] * 0.5)
        retest = _simulate(candles, found + 1, side, retest_stop, atr[found], cost=0.30)
        if retest is None:
            continue
        # Retest must also enter and exit before the same split boundary.
        if found + 1 >= split_end or (retest.get("exit_timestamp") is not None
                                      and int(retest["exit_timestamp"]) >= int(candles[split_end - 1]["timestamp"])):
            continue
        pairs.append({
            "event_id": f"{candles[i].get('timestamp')}:{side}",
            "breakout_timestamp": candles[i].get("timestamp"),
            "side": "long" if side == 1 else "short",
            "regime": _regime(close, e50, e200, i),
            "split": split,
            "direct": direct,
            "retest": retest,
            "paired_delta_net_r": retest["net_r"] - direct["net_r"],
            "paired_delta_net_pct": retest["net_return_pct"] - direct["net_return_pct"],
        })
    return pairs, unmatched, direct_all


def _stats(trades, cost=0.30):
    if not trades:
        return {"n": 0, "win_rate_pct": None, "mean_net_pct": None, "median_net_pct": None,
                "mean_net_r": None, "profit_factor": None}
    rets = [t["gross_return_pct"] - cost for t in trades]
    rs = [(t["gross_return_pct"] - cost) / t["risk_pct"] for t in trades if t["risk_pct"] > 0]
    gp = sum(x for x in rets if x > 0)
    gl = abs(sum(x for x in rets if x < 0))
    return {
        "n": len(trades), "win_rate_pct": round(sum(x > 0 for x in rets) / len(rets) * 100, 2),
        "mean_net_pct": round(mean(rets), 4), "median_net_pct": round(median(rets), 4),
        "mean_net_r": round(mean(rs), 4),
        "profit_factor": round(gp / gl, 4) if gl else None,
    }


def moving_block_bootstrap(values, *, iterations=5000, block=BLOCK_LENGTH, seed=42):
    """Circular moving-block bootstrap of chronological paired deltas."""
    if len(values) < 20:
        return {"n": len(values), "ci95_low": None, "ci95_high": None,
                "prob_delta_positive": None, "status": "insufficient_for_bootstrap"}
    rng = random.Random(seed)
    n = len(values)
    means = []
    blocks_needed = (n + block - 1) // block
    for _ in range(iterations):
        sample = []
        for _b in range(blocks_needed):
            start = rng.randrange(n)
            sample.extend(values[(start + k) % n] for k in range(block))
        means.append(sum(sample[:n]) / n)
    means.sort()
    return {
        "n": n, "block_length_events": block, "iterations": iterations,
        "ci95_low": round(means[int(iterations * 0.025)], 5),
        "ci95_high": round(means[min(iterations - 1, int(iterations * 0.975))], 5),
        "prob_delta_positive": round(sum(x > 0 for x in means) / iterations, 4),
        "status": "moving_block_descriptive_interval",
    }


def _summarize_pairs(pairs):
    result = {}
    for split in ("exploration", "validation", "final_holdout"):
        subset = [p for p in pairs if p["split"] == split]
        result[split] = {}
        for label in ("all", "long", "short", "bullish", "bearish", "sideways_or_transition"):
            group = subset if label == "all" else [
                p for p in subset if (p["side"] if label in ("long", "short") else p["regime"]) == label
            ]
            direct = [p["direct"] for p in group]
            retest = [p["retest"] for p in group]
            result[split][label] = {
                "cost_sensitivity": {
                    str(cost): {
                        "direct": _stats(direct, cost), "retest": _stats(retest, cost),
                        "mean_paired_delta_net_r": round(mean([
                            (p["retest"]["gross_return_pct"] - cost) / p["retest"]["risk_pct"]
                            - (p["direct"]["gross_return_pct"] - cost) / p["direct"]["risk_pct"]
                            for p in group if p["direct"]["risk_pct"] > 0 and p["retest"]["risk_pct"] > 0
                        ]), 5) if group else None,
                    } for cost in COSTS
                },
                "bootstrap_delta_net_r_at_0_30": moving_block_bootstrap(
                    [p["paired_delta_net_r"] for p in group]
                ),
            }
    return result


def _summarize_direct(trades):
    result = {}
    for split in ("exploration", "validation", "final_holdout"):
        rows = [p["direct"] for p in trades if p["split"] == split]
        result[split] = _stats(rows)
    return result


def analyze_asset(candles, selected_window):
    variants = {}
    selected_pairs = []
    selected_direct = []
    for w in WINDOWS:
        pairs, unmatched, direct_all = build_pairs(candles, w)
        summary = _summarize_pairs(pairs)
        variants[str(w)] = {
            "exploration": summary["exploration"],
            "validation": summary["validation"],
            "breakouts_without_valid_retest": len(unmatched),
        }
        if selected_window == w:
            selected_pairs = pairs
            selected_direct = direct_all
    if selected_window is None:
        return {"frozen_window": None, "status": "insufficient_exploration_sample",
                "window_diagnostics_exploration_validation_only": variants}
    final = [p for p in selected_pairs if p["split"] == "final_holdout"]
    validation = [p for p in selected_pairs if p["split"] == "validation"]
    direct_final = [p for p in selected_direct if p["split"] == "final_holdout"]
    direct_validation = [p for p in selected_direct if p["split"] == "validation"]
    return {
        "frozen_window_selected_globally_from_exploration": selected_window,
        "window_diagnostics_exploration_validation_only": variants,
        "all_breakout_direct_benchmark_validation": _summarize_direct(direct_validation),
        "validation_frozen_window": _summarize_pairs(validation)["validation"],
        "all_breakout_direct_benchmark_final": _summarize_direct(direct_final),
        "untouched_final_holdout": {
            "window": selected_window, "matched_pairs": len(final),
            "summary": _summarize_pairs(final)["final_holdout"],
            "notice": "Only the single globally selected window is evaluated; final data is excluded from all window diagnostics and must not be used to retune.",
        },
    }


def run(symbols, limit):
    client = BinanceMarketDataClient()
    raw_assets, unavailable = [], []
    for symbol in symbols:
        try:
            candles = closed_candles(client.get_klines_history(symbol, interval="1d", total_limit=limit))
            if len(candles) < 500:
                unavailable.append({"symbol": symbol, "reason": f"only {len(candles)} closed daily candles"})
                continue
            per_window = {}
            for w in WINDOWS:
                pairs, unmatched, direct_all = build_pairs(candles, w)
                per_window[str(w)] = {"pairs": pairs, "unmatched": unmatched, "direct_all": direct_all}
            raw_assets.append({"symbol": symbol, "candles": candles, "per_window": per_window})
        except (BinanceMarketDataError, ValueError) as exc:
            unavailable.append({"symbol": symbol, "reason": str(exc)})
    # One global window is frozen using pooled exploration data only, not per-asset tuning.
    pooled = {}
    for w in WINDOWS:
        rows = [p for a in raw_assets for p in a["per_window"][str(w)]["pairs"]
                if p["split"] == "exploration"]
        pooled[str(w)] = {
            "pairs": len(rows),
            "mean_paired_delta_net_r": mean([p["paired_delta_net_r"] for p in rows]) if rows else None,
        }
    eligible = [(v["mean_paired_delta_net_r"], int(w), v["pairs"])
                for w, v in pooled.items() if v["pairs"] >= 30]
    selected = max(eligible)[1] if eligible else None
    assets = []
    for a in raw_assets:
        assets.append({
            "symbol": a["symbol"], "candles": len(a["candles"]),
            "first_date": a["candles"][0].get("date"), "last_date": a["candles"][-1].get("date"),
            "analysis": analyze_asset(a["candles"], selected),
        })
    return {
        "report_type": "paired_breakout_retest_final_holdout_v1",
        "methodology": {
            "timeframe": "1d", "history_limit_per_asset": limit,
            "assets_requested": symbols, "retest_windows": list(WINDOWS),
            "chronological_partitions": "60% exploration / 20% validation / 20% final untouched holdout, assigned by breakout candle index",
            "paired_unit": "same qualifying breakout event; compare direct next-open entry with retest-confirmation next-open entry",
            "exit_equivalence": "same 2R target, five-bar maximum holding period, stop-first OHLC convention, gap-through stop at open, and fixed round-trip costs",
            "stop_geometry": "strategy-specific structural stop: breakout candle extreme for direct, retest candle extreme for retest; compare risk-normalized net R and net percentage separately",
            "cost_scenarios_pct": list(COSTS),
            "bootstrap": "circular moving-block bootstrap on chronological paired event deltas, block length 5, 5000 resamples; descriptive only",
            "selection": "one global window selected across pooled assets using exploration paired mean net-R only; validation assesses frozen selection; final period reports only that frozen window",
            "exploration_window_comparison": pooled,
            "frozen_global_window": selected,
            "subgroups": "long/short and EMA50/EMA200 regime at breakout close",
            "benchmark": "Unconditional direct-breakout benchmark includes every eligible direct breakout signal, whether or not a retest subsequently occurs; paired comparison is reported separately on the retest-eligible subset.",
            "partition_purge": "A trade is retained only when its entry and exit are inside the same chronological partition; boundary-crossing trades are excluded.",
            "regime_definition": "Bullish/bearish require price and EMA50/EMA200 alignment; all other EMA states are classified as sideways_or_transition. This is descriptive, not a strategy entry filter.",
            "warning": "Paired sample remains conditional on a subsequent valid retest; compare against the all-breakout direct benchmark as well. Asset-level block intervals are descriptive; global date-cluster bootstrap is reported separately.",
        },
        "assets": assets, "unavailable": unavailable,
        "safety": "Read-only public Binance Spot data. No exchange credentials, order APIs, scanner, paper ledger, positions or production settings touched.",
    }


def main():
    p = argparse.ArgumentParser(description="Paired breakout/retest study with untouched final holdout")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--limit", type=int, default=5000, choices=(1000, 2000, 3000, 5000, 7500, 10000))
    p.add_argument("--output", default="reports/paired_breakout_retest_final_holdout.json")
    args = p.parse_args()
    report = run(args.symbols, args.limit)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved paired study for {len(report['assets'])} assets; unavailable={len(report['unavailable'])}: {out}")
    return 0 if report["assets"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
