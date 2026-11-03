"""Second-stage robustness checks for breakout-retest research. Read-only only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError
from global_markets.statistical_intelligence import closed_candles, _ema
from tools.run_breakout_retest_research import evaluate
from tools.run_breakout_retest_matrix import DEFAULT_SYMBOLS


COSTS = (0.30, 0.50, 0.75)


def _stats(trades: list[dict], cost: float) -> dict:
    returns = [float(t["gross_return_pct"]) - cost for t in trades]
    wins = [v for v in returns if v > 0]
    losses = [v for v in returns if v < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": len(returns),
        "win_rate_pct": round(len(wins) / len(returns) * 100, 1) if returns else None,
        "mean_net_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "median_net_return_pct": round(sorted(returns)[len(returns)//2], 3) if returns else None,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (None if not returns else 0.0),
        "sample_status": "descriptive_only" if len(returns) < 30 else "exploration_floor_met_not_proof",
    }


def _regimes(candles: list[dict]) -> dict:
    closes = [float(c["close"]) for c in candles]
    e50, e200 = _ema(closes, 50), _ema(closes, 200)
    result = {}
    for i, c in enumerate(candles):
        if e50[i] is None or e200[i] is None:
            label = "unclassified"
        elif closes[i] > e50[i] > e200[i]:
            label = "bullish"
        elif closes[i] < e50[i] < e200[i]:
            label = "bearish"
        else:
            label = "sideways_or_transition"
        result[c.get("timestamp") or c.get("date")] = label
    return result


def _bootstrap_mean_ci(values: list[float], *, iterations: int = 3000, seed: int = 42) -> dict:
    """Simple IID percentile interval; descriptive only, not valid for dependent trades."""
    if len(values) < 10:
        return {"lower_95_pct": None, "upper_95_pct": None, "status": "too_few_trades"}
    import random
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(iterations))
    return {"lower_95_pct": round(means[int(iterations * 0.025)], 3),
            "upper_95_pct": round(means[min(iterations - 1, int(iterations * 0.975))], 3),
            "status": "iid_descriptive_interval_dependence_not_modelled"}


def _breakout_only_baseline(candles: list[dict], *, cost: float = 0.30) -> list[dict]:
    """Enter next open on every qualifying breakout; same 2R/5-bar exit convention.

    This is a distinct benchmark with no retest filter. It uses only information
    available at breakout close; it is not a claim of identical risk geometry.
    """
    n = len(candles)
    close = [float(c["close"]) for c in candles]
    volume = [float(c.get("volume", 0) or 0) for c in candles]
    e50, e200 = _ema(close, 50), _ema(close, 200)
    e12, e26 = _ema(close, 12), _ema(close, 26)
    macd = [e12[i] - e26[i] if e12[i] is not None and e26[i] is not None else None for i in range(n)]
    sig = _ema([x if x is not None else 0.0 for x in macd], 9)
    from global_markets.statistical_intelligence import _rsi, _atr, _sma
    rsi, atr, vavg = _rsi(close), _atr(candles), _sma(volume, 20)
    split = int(n * 0.70)
    trades, i = [], 200
    while i < n - 6:
        p, b = candles[i-1], candles[i]
        vals = (e50[i], e200[i], rsi[i], atr[i], vavg[i], macd[i], sig[i])
        if any(x is None for x in vals) or atr[i] <= 0 or not vavg[i]:
            i += 1
            continue
        vol_ok = volume[i] >= vavg[i] * 1.20
        side = 1 if (b["close"] > p["high"] and b["close"] > e50[i] > e200[i]
                     and 50 <= rsi[i] <= 70 and macd[i] > sig[i] and vol_ok) else (
               -1 if (b["close"] < p["low"] and b["close"] < e50[i] < e200[i]
                     and 30 <= rsi[i] <= 50 and macd[i] < sig[i] and vol_ok) else 0)
        if not side:
            i += 1
            continue
        entry_i = i + 1
        entry = float(candles[entry_i]["open"])
        level = float(p["high"] if side > 0 else p["low"])
        buffer = float(atr[i]) * 0.5
        stop = min(float(b["low"]), level - buffer) if side > 0 else max(float(b["high"]), level + buffer)
        risk = abs(entry - stop)
        if risk <= 0 or (side > 0 and stop >= entry) or (side < 0 and stop <= entry):
            i += 1
            continue
        target = entry + side * risk * 2
        last = min(entry_i + 4, n - 1)
        exit_price, exit_i = float(candles[last]["close"]), last
        reason = "time_exit"
        for k in range(entry_i, last + 1):
            x = candles[k]
            if (side > 0 and x["open"] <= stop) or (side < 0 and x["open"] >= stop):
                exit_price, exit_i, reason = float(x["open"]), k, "stop_gap"
                break
            stop_hit = x["low"] <= stop if side > 0 else x["high"] >= stop
            target_hit = x["high"] >= target if side > 0 else x["low"] <= target
            if stop_hit:
                exit_price, exit_i, reason = stop, k, "stop_loss"
                break
            if target_hit:
                exit_price, exit_i, reason = target, k, "take_profit"
                break
        gross = (exit_price / entry - 1) * 100 * side
        trades.append({"breakout_timestamp": b.get("timestamp"), "side": "long" if side > 0 else "short",
                       "gross_return_pct": gross, "holdout": i >= split, "exit_reason": reason})
        i = exit_i + 1
    return trades


def summarize(candles: list[dict], window: int) -> dict:
    result = evaluate(candles, retest_window=window)
    trades = result["trades"]
    regimes = _regimes(candles)
    split_report = {}
    for split, is_holdout in (("exploration", False), ("holdout", True)):
        subset = [t for t in trades if bool(t["holdout"]) is is_holdout]
        split_report[split] = {
            "overall": {str(c): _stats(subset, c) for c in COSTS},
            "long": {str(c): _stats([t for t in subset if t["side"] == "long"], c) for c in COSTS},
            "short": {str(c): _stats([t for t in subset if t["side"] == "short"], c) for c in COSTS},
            "by_regime": {
                r: {str(c): _stats([t for t in subset if regimes.get(t.get("breakout_timestamp")) == r], c)
                    for c in COSTS}
                for r in ("bullish", "bearish", "sideways_or_transition", "unclassified")
            },
            "per_trade_iid_ci_at_0_30": _bootstrap_mean_ci(
                [float(t["gross_return_pct"]) - 0.30 for t in subset]
            ),
        }
    baseline = _breakout_only_baseline(candles)
    return {
        "retest": split_report,
        "breakout_only_baseline": {
            split: {str(c): _stats([t for t in baseline if bool(t["holdout"]) is is_holdout], c)
                    for c in COSTS}
            for split, is_holdout in (("exploration", False), ("holdout", True))
        },
        "trade_counts_by_side": {
            side: sum(t["side"] == side for t in trades) for side in ("long", "short")
        },
        "limitations": [
            "The breakout-only benchmark is a separate strategy, not an identical-risk matched control.",
            "The benchmark has no retest condition; it enters at the next candle open.",
            "IID bootstrap intervals ignore serial dependence, overlapping market regimes and cross-asset correlation.",
            "Subgroup and cost-sensitivity results are descriptive; repeated comparisons increase false-discovery risk.",
            "OHLC bars cannot establish intrabar ordering; stop is assumed before target when both touch.",
            "Fees and slippage are fixed assumptions; real spreads, funding and market impact are not modelled.",
        ],
    }


def run(symbols: list[str], intervals: list[str], limit: int) -> dict:
    client = BinanceMarketDataClient()
    assets, unavailable = [], []
    for symbol in symbols:
        for interval in intervals:
            try:
                candles = closed_candles(client.get_klines_history(symbol, interval=interval, total_limit=limit))
                if len(candles) < 250:
                    unavailable.append({"symbol": symbol, "interval": interval, "reason": "fewer than 250 closed candles"})
                    continue
                assets.append({
                    "symbol": symbol, "interval": interval, "candles": len(candles),
                    "first_date": candles[0].get("date"), "last_date": candles[-1].get("date"),
                    "windows": {str(w): summarize(candles, w) for w in (2, 3, 5)},
                })
            except (BinanceMarketDataError, ValueError) as exc:
                unavailable.append({"symbol": symbol, "interval": interval, "reason": str(exc)})
    return {
        "report_type": "read_only_breakout_retest_robustness_validation",
        "methodology": {
            "intervals": intervals, "history_limit": limit, "cost_scenarios_round_trip_pct": list(COSTS),
            "chronological_split": "70% exploration / 30% holdout",
            "regimes": "EMA50/EMA200 at breakout close",
            "benchmark": "all qualifying breakouts entered next candle open, without retest filter",
            "minimum_sample": "30 trades is only a descriptive floor, not statistical proof",
        },
        "assets": assets, "unavailable": unavailable,
        "safety": "Read-only public Binance Spot research. No scanner, portfolio, orders, credentials or production settings touched.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Second-stage read-only robustness validation")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--intervals", nargs="+", choices=("4h", "1d"), default=("4h", "1d"))
    p.add_argument("--limit", type=int, choices=(1000, 2000, 3000, 5000), default=5000)
    p.add_argument("--output", default="reports/breakout_retest_robustness_latest.json")
    a = p.parse_args()
    report = run(a.symbols, a.intervals, a.limit)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved robustness validation for {len(report['assets'])} asset/interval pairs to {out}")
    return 0 if report["assets"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
