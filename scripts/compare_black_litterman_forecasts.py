"""Fetch read-only price history and emit a model-comparison report."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio_engine.data.coingecko_history import fetch_watchlist_history
from portfolio_engine.forecast.comparison import build_model_comparison_report


def _aligned_prices(asset_series: dict, benchmark_series: dict) -> tuple[list[str], np.ndarray, np.ndarray]:
    asset = dict(zip(asset_series["dates"], asset_series["closes"]))
    benchmark = dict(zip(benchmark_series["dates"], benchmark_series["closes"]))
    dates = sorted(set(asset).intersection(benchmark))
    if len(dates) < 120:
        raise ValueError("fewer than 120 common daily observations with BTC")
    parsed = [date.fromisoformat(value) for value in dates]
    if any((current - previous).days != 1 for previous, current in zip(parsed, parsed[1:])):
        raise ValueError("common history contains missing calendar days")
    return dates, np.asarray([asset[value] for value in dates]), np.asarray([benchmark[value] for value in dates])


def build_watchlist_report(history: dict, *, min_train_samples: int = 30) -> dict:
    series = history.get("series", {})
    if "BTCUSD" not in series:
        return {
            "status": "insufficient_history",
            "source": history.get("source"),
            "quote_currency": history.get("quote_currency", "USD"),
            "observed_at": history.get("observed_at"),
            "assets": {},
            "unavailable": list(history.get("unavailable", [])),
            "reason": "BTCUSD history is required as the common benchmark.",
            "read_only": True,
            "portfolio_eligibility_changed": False,
        }
    reports, unavailable = {}, list(history.get("unavailable", []))
    for symbol, item in series.items():
        try:
            dates, prices, btc_prices = _aligned_prices(item, series["BTCUSD"])
            report = build_model_comparison_report(
                prices, min_train_samples=min_train_samples,
                benchmark_prices=None if symbol == "BTCUSD" else btc_prices,
            )
            report["history_start"] = dates[0]
            report["history_end"] = dates[-1]
            reports[symbol] = report
        except (ValueError, ArithmeticError) as exc:
            unavailable.append({"symbol": symbol, "reason": "comparison_failed", "detail": str(exc)})
    return {
        "status": "research_only",
        "source": history.get("source"),
        "quote_currency": history.get("quote_currency", "USD"),
        "observed_at": history.get("observed_at"),
        "assets": reports,
        "unavailable": unavailable,
        "read_only": True,
        "portfolio_eligibility_changed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365, help="CoinGecko history window (90–365 days)")
    parser.add_argument("--min-train-samples", type=int, default=30)
    parser.add_argument("--output", type=Path, help="Optional JSON output path; otherwise print to stdout")
    args = parser.parse_args()
    history = fetch_watchlist_history(days=args.days)
    report = build_watchlist_report(history, min_train_samples=args.min_train_samples)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print("Wrote model-comparison report to {}".format(args.output))
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
