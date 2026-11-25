"""Read-only adapter for the CORE-041 strategy validation dataset.

The API exposes closed simulation trades and current scanner candidates only.
It never mutates scanner state or places exchange orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scanner.store import ScannerStore


class StrategyValidationFeedError(RuntimeError):
    """Raised when the scanner dataset cannot be read safely."""


def _aware_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_closed_trade(trade: dict) -> dict:
    """Convert one scanner paper trade to a currency-explicit validation record.

    Gross P&L is calculated from reference prices (before simulated execution
    costs). Net P&L is the persisted realized P&L after fees and slippage.
    Costs are exposed only when the required source fields are complete and
    the resulting cost is non-negative within floating-point tolerance.
    """
    issues: list[str] = []
    asset = str(trade.get("asset") or "").strip().upper()
    raw_direction = trade.get("direction")
    direction = str(raw_direction).strip().lower() if raw_direction is not None else ""
    symbol = f"{asset}USDT" if asset else None
    closed_at = _aware_timestamp(trade.get("closed_at"))
    if not symbol:
        issues.append("missing_asset")
    if not direction:
        issues.append("missing_direction")
    elif direction not in {"long", "short"}:
        issues.append("unsupported_direction")
    if closed_at is None:
        issues.append("missing_or_invalid_closed_at")

    try:
        quantity = float(trade["quantity"])
        entry = float(trade["entry_reference_price"])
        exit_price = float(trade["exit_reference_price"])
        net_pnl = float(trade["realized_pnl_usd"])
        if quantity <= 0 or entry <= 0 or exit_price <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        quantity = entry = exit_price = net_pnl = None
        issues.append("missing_or_invalid_execution_values")

    gross_pnl = total_cost = None
    if quantity is not None and direction in {"long", "short"}:
        gross_pnl = quantity * (exit_price - entry)
        if direction == "short":
            gross_pnl = -gross_pnl
        total_cost = gross_pnl - net_pnl
        if total_cost < -0.000001:
            gross_pnl = total_cost = None
            issues.append("inconsistent_gross_net_cost_relationship")
        else:
            total_cost = max(0.0, total_cost)

    if net_pnl is None:
        issues.append("missing_net_pnl")
    if total_cost is None:
        issues.append("execution_costs_unavailable")

    return {
        "trade_id": str(trade.get("position_id") or trade.get("trade_id") or ""),
        "symbol": symbol,
        "direction": direction if direction in {"long", "short"} else None,
        "closed_at": closed_at,
        "quote_currency": "USDT",
        "gross_pnl": gross_pnl,
        "total_cost": total_cost,
        "net_pnl": net_pnl,
        "cost_status": "complete" if total_cost is not None else "incomplete",
        "data_quality_issues": issues,
    }


class StrategyValidationReadService:
    """Read scanner candidates and normalized closed paper trades."""

    def __init__(self, store_factory=ScannerStore):
        self.store_factory = store_factory

    def dataset(self, *, symbol: str | None = None, limit: int = 500) -> dict:
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000")
        canonical_symbol = symbol.strip().upper() if symbol else None
        if canonical_symbol and (not canonical_symbol.endswith("USDT") or len(canonical_symbol) <= 4):
            raise ValueError("symbol must be a canonical USDT spot pair")

        try:
            store = self.store_factory()
            state = store.load_state()
            candidates = store.latest_candidates(limit=min(limit, 500))
        except Exception as exc:
            raise StrategyValidationFeedError("Scanner dataset is unavailable") from exc

        raw_trades = state.get("closed_trades", []) if isinstance(state, dict) else []
        if not isinstance(raw_trades, list):
            raise StrategyValidationFeedError("Scanner closed-trade ledger has an invalid shape")

        trades = [normalize_closed_trade(row) for row in raw_trades if isinstance(row, dict)]
        if canonical_symbol:
            trades = [row for row in trades if row.get("symbol") == canonical_symbol]
            candidates = [row for row in candidates if str(row.get("symbol", "")).upper() == canonical_symbol]
        trades.sort(key=lambda row: row.get("closed_at") or "")
        trades = trades[-limit:]

        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "crypto-research-market-scanner-paper-ledger",
            "read_only": True,
            "mode": "simulation_only",
            "quote_currency": "USDT",
            "trade_count": len(trades),
            "cost_incomplete_count": sum(1 for row in trades if row["total_cost"] is None),
            "trades": trades,
            "candidates": candidates,
            "limitations": [
                "Only closed Market Scanner paper trades are included.",
                "The ledger contains simulation results, not live executions.",
                "Costs are reconstructed from reference-price gross P&L and persisted net P&L.",
                "Missing or inconsistent source values remain unavailable; they are never replaced with zero.",
                "This endpoint does not expose portfolio writes or exchange execution.",
            ],
        }
