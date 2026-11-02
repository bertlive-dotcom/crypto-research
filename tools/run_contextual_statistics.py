"""Run isolated hourly contextual statistics on Binance Spot candles.

Example: python tools/run_contextual_statistics.py --limit 1000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError
from global_markets.contextual_statistics import analyze_context


def main():
    parser = argparse.ArgumentParser(description="Read-only hourly context statistics")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--limit", type=int, default=1000, choices=range(200, 1001))
    parser.add_argument("--output", default="contextual_statistics_report.json")
    args = parser.parse_args()
    client = BinanceMarketDataClient()
    assets, failures = [], []
    for symbol in args.symbols:
        try:
            rows = client.get_klines(symbol, interval="1h", limit=args.limit)
            assets.append(analyze_context(rows, symbol=symbol))
        except (BinanceMarketDataError, ValueError) as exc:
            failures.append({"symbol": symbol, "reason": str(exc)})
    payload = {
        "report_type": "read_only_hourly_context_statistics",
        "read_only": True,
        "assets": assets,
        "unavailable": failures,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(assets)} contextual reports to {args.output}")
    if failures:
        print(f"{len(failures)} asset requests failed; see unavailable in report")
    return 0 if assets else 1


if __name__ == "__main__":
    raise SystemExit(main())
