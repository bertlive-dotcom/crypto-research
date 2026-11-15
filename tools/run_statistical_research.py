"""Run a read-only daily pattern study for BTC, ETH and SOL on Binance Spot.

Usage:
    python tools/run_statistical_research.py
    python tools/run_statistical_research.py --symbols BTCUSDT ETHUSDT SOLUSDT --limit 1000

The report is written to statistical_research_report.json. No API keys or
exchange account permissions are used; this script never places orders.
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
from global_markets.statistical_intelligence import analyze_pattern_history


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical crypto pattern research (read-only)")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--limit", type=int, default=1000, choices=range(60, 1001))
    parser.add_argument("--output", default="statistical_research_report.json")
    args = parser.parse_args()

    client = BinanceMarketDataClient()
    reports = []
    failures = []
    for symbol in args.symbols:
        try:
            candles = client.get_klines(symbol, interval="1d", limit=args.limit)
            reports.append(analyze_pattern_history(candles, symbol=symbol))
        except (BinanceMarketDataError, ValueError) as error:
            failures.append({"symbol": symbol, "reason": str(error)})

    payload = {
        "report_type": "descriptive_historical_pattern_research",
        "read_only": True,
        "assets": reports,
        "unavailable": failures,
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(reports)} asset reports to {output}")
    if failures:
        print(f"{len(failures)} asset requests failed; see unavailable in the report")
    return 0 if reports else 1


if __name__ == "__main__":
    raise SystemExit(main())
