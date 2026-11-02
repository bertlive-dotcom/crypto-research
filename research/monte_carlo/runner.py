"""Run read-only Monte Carlo analysis on breakout-retest research JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.monte_carlo.simulator import simulate, trades_to_r_multiples


def _trade_rows(asset: dict) -> list[dict]:
    """Accept both the current flat report schema and the legacy nested schema."""
    if isinstance(asset.get("trades"), list):
        return asset["trades"]
    study = asset.get("breakout_retest", {})
    if isinstance(study, dict) and isinstance(study.get("trades"), list):
        return study["trades"]
    return []


def build_report(source: dict, *, simulations: int = 10_000,
                 risk_per_trade_pct: float = 1.0, block_size: int = 3,
                 ruin_drawdown_pct: float = 20.0, seed: int = 42) -> dict:
    assets = []
    for asset in source.get("assets", []):
        rows = _trade_rows(asset)
        result = {"symbol": asset.get("symbol"), "sample": {}}
        if not rows:
            result["status"] = "no_trades"
            assets.append(result)
            continue

        for segment in ("exploration", "holdout"):
            segment_rows = [
                row for row in rows
                if bool(row.get("holdout")) == (segment == "holdout")
            ]
            if not segment_rows:
                result["sample"][segment] = {"status": "no_trades", "sample_trades": 0}
                continue

            required = ("entry", "stop", "net_return_pct")
            missing = sorted({
                field for row in segment_rows for field in required
                if field not in row or row[field] is None
            })
            if missing:
                result["sample"][segment] = {
                    "status": "incomplete_trade_data",
                    "sample_trades": len(segment_rows),
                    "valid_trades": 0,
                    "missing_fields": missing,
                    "message": (
                        "Regenerate the source report with entry and stop prices; "
                        "net R cannot be inferred from net_return_pct alone."
                    ),
                }
                continue

            try:
                r_values = trades_to_r_multiples(segment_rows)
            except (TypeError, ValueError) as exc:
                result["sample"][segment] = {
                    "status": "invalid_trade_data",
                    "sample_trades": len(segment_rows),
                    "valid_trades": 0,
                    "error": str(exc),
                }
                continue

            if len(r_values) < 10:
                result["sample"][segment] = {
                    "status": "insufficient_sample",
                    "sample_trades": len(r_values),
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
            "Net R requires entry, stop and net_return_pct; it cannot be inferred from percentage return alone.",
            "The historical report may predate the addition of entry/stop fields and must be regenerated before simulation.",
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
