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
    pairs, unmatched = [], []
    # Split by breakout timestamp, not by trade exit, so a trade cannot migrate between partitions.
    cut1, cut2 = int(n * 0.60), int(n * 0.80)
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
        split = "exploration" if i < cut1 else ("validation" if i < cut2 else "final_holdout")
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
    return pairs, unmatched


def _stats(trades):
    if not trades:
        return {"n": 0, "win_rate_pct": None, "mean_net_pct": None, "median_net_pct": None,
                "mean_net_r": None, "profit_factor": None}
    rets = [t["net_return_pct"] for t in trades]
    rs = [t["net_r"] for t in trades]
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
                "direct": _stats(direct), "retest": _stats(retest),
                "mean_paired_delta_net_r": round(mean([p["paired_delta_net_r"] for p in group]), 5) if group else None,
                "mean_paired_delta_net_pct": round(mean([p["paired_delta_net_pct"] for p in group]), 5) if group else None,
                "bootstrap_delta_net_r": moving_block_bootstrap(
                    [p["paired_delta_net_r"] for p in group]
                ),
            }
    return result


def analyze_asset(candles):
    variants = {}
    for w in WINDOWS:
        pairs, unmatched = build_pairs(candles, w)
        variants[str(w)] = {
            "summary": _summarize_pairs(pairs),
            "matched_pairs": pairs,
            "breakouts_without_valid_retest": len(unmatched),
            "unmatched_breakout_examples": unmatched[:20],
        }
    # Freeze the single configuration using exploration only.
    candidates = []
    for w in WINDOWS:
        rows = variants[str(w)]["matched_pairs"]
        exp = [p for p in rows if p["split"] == "exploration"]
        delta = mean([p["paired_delta_net_r"] for p in exp]) if len(exp) >= 20 else float("-inf")
        candidates.append((delta, w, len(exp)))
    _, selected, exp_n = max(candidates)
    selected_pairs = variants[str(selected)]["matched_pairs"]
    validation = [p for p in selected_pairs if p["split"] == "validation"]
    final = [p for p in selected_pairs if p["split"] == "final_holdout"]
    # Final period is evaluated only for the frozen exploration-selected window.
    return {
        "selected_window_from_exploration_only": selected if exp_n >= 20 else None,
        "selection_exploration_pair_count": exp_n,
        "variants_exploration_and_validation": {
            w: {
                split: variants[str(w)]["summary"][split]["all"]
                for split in ("exploration", "validation")
            } for w in WINDOWS
        },
        "frozen_validation": {
            "window": selected if exp_n >= 20 else None,
            "matched_pairs": len(validation),
            "summary": variants[str(selected)]["summary"]["validation"]["all"] if exp_n >= 20 else None,
        },
        "untouched_final_holdout": {
            "window": selected if exp_n >= 20 else None,
            "matched_pairs": len(final) if exp_n >= 20 else 0,
            "summary": variants[str(selected)]["summary"]["final_holdout"]["all"] if exp_n >= 20 else None,
            "notice": "Only the single exploration-selected window is evaluated here; final results must not be used to retune.",
        },
        "full_diagnostics": variants,
    }


def run(symbols, limit):
    client = BinanceMarketDataClient()
    assets, unavailable = [], []
    for symbol in symbols:
        try:
            candles = closed_candles(client.get_klines_history(symbol, interval="1d", total_limit=limit))
            if len(candles) < 500:
                unavailable.append({"symbol": symbol, "reason": f"only {len(candles)} closed daily candles"})
                continue
            assets.append({
                "symbol": symbol, "candles": len(candles),
                "first_date": candles[0].get("date"), "last_date": candles[-1].get("date"),
                "analysis": analyze_asset(candles),
            })
        except (BinanceMarketDataError, ValueError) as exc:
            unavailable.append({"symbol": symbol, "reason": str(exc)})
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
            "selection": "window selected per asset using exploration paired mean net-R only; validation assesses frozen selection; final period reports only that frozen window",
            "subgroups": "long/short and EMA50/EMA200 regime at breakout close",
            "warning": "Events are matched within asset; cross-asset correlation is not jointly resampled. Block bootstrap is descriptive and does not cure multiple-testing or sparse-sample risks.",
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
