"""Read-only Monte Carlo risk analysis for historical research trades.

This module never places orders and has no exchange or execution dependencies.
"""
from __future__ import annotations

import math
import random
from statistics import mean
from typing import Iterable


def trades_to_r_multiples(trades: Iterable[dict]) -> list[float]:
    """Convert research trade rows to net R using entry-to-stop price risk.

    Existing breakout-retest reports store net_return_pct as a percentage of
    notional and include entry/stop. R is therefore net_return_pct divided by
    the absolute entry-to-stop percentage. Rows without these fields are
    rejected rather than silently treating notional returns as R.
    """
    values: list[float] = []
    for index, trade in enumerate(trades):
        try:
            entry = float(trade["entry"])
            stop = float(trade["stop"])
            net_pct = float(trade["net_return_pct"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Trade {index} is missing valid entry, stop or net_return_pct") from exc
        if not all(math.isfinite(x) for x in (entry, stop, net_pct)) or entry <= 0:
            raise ValueError(f"Trade {index} contains non-finite values or invalid entry")
        risk_pct = abs(entry - stop) / entry * 100.0
        if risk_pct <= 0:
            raise ValueError(f"Trade {index} has zero price risk")
        values.append(net_pct / risk_pct)
    return values


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("Cannot calculate percentile of an empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _sample_iid(values: list[float], size: int, rng: random.Random) -> list[float]:
    return [rng.choice(values) for _ in range(size)]


def _sample_blocks(values: list[float], size: int, block_size: int,
                   rng: random.Random) -> list[float]:
    """Non-circular moving-block bootstrap; preserve local trade ordering."""
    result: list[float] = []
    max_start = max(0, len(values) - block_size)
    while len(result) < size:
        start = rng.randint(0, max_start)
        result.extend(values[start:start + block_size])
    return result[:size]


def _path_metrics(r_values: list[float], risk_pct: float,
                  ruin_drawdown_pct: float) -> dict:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    losing_streak = 0
    max_losing_streak = 0
    ruined = False
    for r_value in r_values:
        equity *= max(0.0, 1.0 + risk_pct / 100.0 * r_value)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100.0 if peak else 100.0
        max_drawdown = max(max_drawdown, drawdown)
        if r_value < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0
        if drawdown >= ruin_drawdown_pct or equity <= 0:
            ruined = True
    return {
        "ending_equity_multiple": equity,
        "net_return_pct": (equity - 1.0) * 100.0,
        "max_drawdown_pct": max_drawdown,
        "max_losing_streak": max_losing_streak,
        "ruin_threshold_hit": ruined,
    }


def simulate(r_multiples: Iterable[float], *, simulations: int = 10_000,
             trades_per_path: int | None = None, risk_per_trade_pct: float = 1.0,
             block_size: int = 3, ruin_drawdown_pct: float = 20.0,
             seed: int = 42) -> dict:
    """Run IID and block-bootstrap paths on a historical net-R sample.

    Risk is a fixed percentage of current equity per trade. This is a research
    assumption, not a position-sizing instruction. Slippage/fees must already
    be reflected in the supplied net R outcomes.
    """
    values = [float(x) for x in r_multiples]
    if not values or not all(math.isfinite(x) for x in values):
        raise ValueError("r_multiples must contain finite numeric observations")
    if simulations < 1 or risk_per_trade_pct <= 0 or risk_per_trade_pct >= 100:
        raise ValueError("Invalid simulations or risk_per_trade_pct")
    if block_size < 1 or ruin_drawdown_pct <= 0 or ruin_drawdown_pct >= 100:
        raise ValueError("Invalid block_size or ruin_drawdown_pct")
    size = trades_per_path or len(values)
    if size < 1:
        raise ValueError("trades_per_path must be positive")
    rng_iid = random.Random(seed)
    rng_block = random.Random(seed + 1)
    iid_paths = [
        _path_metrics(_sample_iid(values, size, rng_iid), risk_per_trade_pct, ruin_drawdown_pct)
        for _ in range(simulations)
    ]
    block_paths = [
        _path_metrics(_sample_blocks(values, size, block_size, rng_block),
                      risk_per_trade_pct, ruin_drawdown_pct)
        for _ in range(simulations)
    ]

    def summarize(paths: list[dict]) -> dict:
        endings = [p["net_return_pct"] for p in paths]
        drawdowns = [p["max_drawdown_pct"] for p in paths]
        streaks = [p["max_losing_streak"] for p in paths]
        return {
            "ending_net_return_pct": {
                "p05": round(_percentile(endings, 5), 3),
                "p25": round(_percentile(endings, 25), 3),
                "p50": round(_percentile(endings, 50), 3),
                "p75": round(_percentile(endings, 75), 3),
                "p95": round(_percentile(endings, 95), 3),
                "mean": round(mean(endings), 3),
            },
            "maximum_drawdown_pct": {
                "p50": round(_percentile(drawdowns, 50), 3),
                "p95": round(_percentile(drawdowns, 95), 3),
                "worst": round(max(drawdowns), 3),
            },
            "max_losing_streak": {
                "p50": round(_percentile(streaks, 50), 2),
                "p95": round(_percentile(streaks, 95), 2),
                "worst": max(streaks),
            },
            "ruin_threshold_probability_pct": round(
                sum(p["ruin_threshold_hit"] for p in paths) / len(paths) * 100, 2
            ),
        }

    return {
        "method": "monte_carlo_bootstrap_risk_research",
        "sample_trades": len(values),
        "simulations": simulations,
        "trades_per_path": size,
        "risk_per_trade_pct": risk_per_trade_pct,
        "block_size": block_size,
        "ruin_drawdown_threshold_pct": ruin_drawdown_pct,
        "seed": seed,
        "iid_bootstrap": summarize(iid_paths),
        "moving_block_bootstrap": summarize(block_paths),
        "limitations": [
            "Historical trade outcomes are resampled; this is not a forecast.",
            "Bootstrap assumes the observed sample is informative about future outcomes.",
            "IID sampling destroys serial dependence; block bootstrap only partially preserves local ordering.",
            "Fixed-fractional risk and the drawdown threshold are user-configurable research assumptions.",
            "Net R conversion relies on the report's entry, stop and net_return_pct fields.",
            "Small samples and regime changes can make simulated tails unstable.",
        ],
    }
