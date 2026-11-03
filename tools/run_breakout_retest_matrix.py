"""Isolated comparison matrix for breakout-retest research (read-only)."""
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


DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "BONKUSDT", "WIFUSDT",
    "PUMPUSDT", "UNIUSDT", "NEARUSDT", "ZECUSDT", "AAVEUSDT", "PEPEUSDT",
]


def _stats(trades: list[dict]) -> dict:
    values = [float(t["net_return_pct"]) for t in trades]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": len(values),
        "wins": len(wins),
        "win_rate_pct": round(len(wins) / len(values) * 100, 1) if values else None,
        "mean_net_return_pct": round(sum(values) / len(values), 3) if values else None,
        "median_net_return_pct": round(sorted(values)[len(values)//2], 3) if values else None,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "sample_status": "usable_for_exploration" if len(values) >= 30 else "small_sample",
    }


def _classify(candles: list[dict]) -> dict[str, str]:
    closes = [float(c["close"]) for c in candles]
    e50, e200 = _ema(closes, 50), _ema(closes, 200)
    labels = {}
    for i, candle in enumerate(candles):
        if e50[i] is None or e200[i] is None:
            label = "unclassified"
        elif closes[i] > e50[i] > e200[i]:
            label = "bullish"
        elif closes[i] < e50[i] < e200[i]:
            label = "bearish"
        else:
            label = "sideways_or_transition"
        labels[candle.get("timestamp") or candle.get("date")] = label
    return labels


def summarize_matrix(candles: list[dict], evaluation: dict) -> dict:
    """Report independent descriptive cuts; do not infer significance."""
    trades = evaluation["trades"]
    regimes = _classify(candles)
    cuts = {}
    for split_name, holdout in (("exploration", False), ("holdout", True)):
        split_trades = [t for t in trades if bool(t["holdout"]) is holdout]
        cuts[split_name] = {
            "all": _stats(split_trades),
            "long": _stats([t for t in split_trades if t["side"] == "long"]),
            "short": _stats([t for t in split_trades if t["side"] == "short"]),
            "by_regime": {
                regime: _stats([t for t in split_trades if regimes.get(t.get("breakout_timestamp") or t["breakout_date"]) == regime])
                for regime in ("bullish", "bearish", "sideways_or_transition", "unclassified")
            },
        }
    return {"cuts": cuts, "trades": trades, "rules": evaluation["rules"],
            "limitations": evaluation["limitations"]}


def run(symbols: list[str], intervals: list[str], limit: int) -> dict:
    client = BinanceMarketDataClient()
    assets, unavailable = [], []
    for symbol in symbols:
        for interval in intervals:
            try:
                rows = closed_candles(client.get_klines_history(
                    symbol, interval=interval, total_limit=limit
                ))
                variants = {}
                for window in (2, 3, 5):
                    result = evaluate(rows, retest_window=window)
                    variants[str(window)] = summarize_matrix(rows, result)
                assets.append({
                    "symbol": symbol, "interval": interval, "candles": len(rows),
                    "first_date": rows[0].get("date") if rows else None,
                    "last_date": rows[-1].get("date") if rows else None,
                    "retest_window_comparison": variants,
                })
            except (BinanceMarketDataError, ValueError) as exc:
                unavailable.append({"symbol": symbol, "interval": interval, "reason": str(exc)})
    return {
        "report_type": "read_only_breakout_retest_comparison_matrix",
        "methodology": {
            "intervals": intervals, "history_limit_per_asset_interval": limit,
            "retest_windows_bars": [2, 3, 5],
            "split": "chronological 70% exploration / 30% holdout",
            "regime": "breakout close relative to EMA50 and EMA200; no future data",
            "long_short": "reported separately",
            "cost_round_trip_pct": 0.30,
            "minimum_sample_for_exploration_label": 30,
            "warning": "The 30-trade label is a descriptive floor, not statistical proof. Multiple comparisons and overlapping signals remain risks.",
        },
        "assets": assets, "unavailable": unavailable,
        "safety": "Research only. No scanner, paper portfolio, order execution, credentials, or production settings are read or modified.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only breakout-retest comparison matrix")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--intervals", nargs="+", choices=("4h", "1d"), default=("4h", "1d"))
    parser.add_argument("--limit", type=int, choices=(1000, 2000, 3000, 5000), default=5000)
    parser.add_argument("--output", default="reports/breakout_retest_matrix_latest.json")
    args = parser.parse_args()
    report = run(args.symbols, args.intervals, args.limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved comparison matrix for {len(report['assets'])} asset/interval pairs to {output}")
    return 0 if report["assets"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
