"""Run read-only Monte Carlo analysis on breakout-retest research JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.monte_carlo.simulator import simulate, trades_to_r_multiples


def build_report(source: dict, *, simulations: int = 10_000,
                 risk_per_trade_pct: float = 1.0, block_size: int = 3,
                 ruin_drawdown_pct: float = 20.0, seed: int = 42) -> dict:
    assets = []
    for asset in source.get("assets", []):
        study = asset.get("breakout_retest", {})
        rows = study.get("trades", [])
        if not rows:
            assets.append({"symbol": asset.get("symbol"), "status": "no_trades"})
            continue
        result = {"symbol": asset.get("symbol"), "sample": {}}
        for segment in ("exploration", "holdout"):
            segment_rows = [row for row in rows if bool(row.get("holdout")) == (segment == "holdout")]
            if not segment_rows:
                result["sample"][segment] = {"status": "no_trades"}
                continue
            r_values = trades_to_r_multiples(segment_rows)
            if len(r_values) < 10:
                result["sample"][segment] = {
                    "status": "insufficient_sample",
                    "trades": len(r_values),
                    "minimum_for_simulation": 10,
                }
                continue
            result["sample"][segment] = {
                "status": "exploratory_simulation",
                **simulate(
                    r_values, simulations=simulations,
                    risk_per_trade_pct=risk_per_trade_pct,
                    block_size=block_size,
                    ruin_drawdown_pct=ruin_drawdown_pct,
                    seed=seed,
                ),
            }
        assets.append(result)
    return {
        "report_type": "read_only_monte_carlo_risk_research",
        "source_report_type": source.get("report_type"),
        "configuration": {
            "simulations": simulations,
            "risk_per_trade_pct": risk_per_trade_pct,
            "block_size": block_size,
            "ruin_drawdown_pct": ruin_drawdown_pct,
            "seed": seed,
        },
        "assets": assets,
        "limitations": [
            "Exploration and holdout are simulated separately; do not use exploration to claim out-of-sample validation.",
            "A minimum of 10 trades is only a technical floor for exploratory simulation, not statistical sufficiency.",
            "This report is isolated research and is not connected to scanner, paper ledger or execution.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Monte Carlo risk report")
    parser.add_argument("--input", required=True, help="Existing breakout-retest JSON report")
    parser.add_argument("--output", default="monte_carlo_risk_report.json")
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--risk-per-trade-pct", type=float, default=1.0)
    parser.add_argument("--block-size", type=int, default=3)
    parser.add_argument("--ruin-drawdown-pct", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = build_report(
        source, simulations=args.simulations,
        risk_per_trade_pct=args.risk_per_trade_pct,
        block_size=args.block_size,
        ruin_drawdown_pct=args.ruin_drawdown_pct,
        seed=args.seed,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved Monte Carlo research report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
