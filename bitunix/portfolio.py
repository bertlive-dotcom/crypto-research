"""Read-only normalization helpers for Bitunix account snapshots.

This module never values assets in fiat and never changes trading state.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def _decimal_text(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    if not number.is_finite():
        return "0"
    return format(number, "f")


def build_portfolio_overview(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Build a display-only overview without mixing real and paper balances."""
    spot_assets = []
    for row in snapshot.get("spot_balances", []) or []:
        if not isinstance(row, Mapping):
            continue
        asset = str(row.get("coin") or row.get("asset") or "").strip()
        if not asset:
            continue
        available = _decimal_text(row.get("balance", row.get("available", 0)))
        locked = _decimal_text(row.get("balanceLocked", row.get("locked", 0)))
        total = format(Decimal(available) + Decimal(locked), "f")
        spot_assets.append({
            "asset": asset,
            "available": available,
            "locked": locked,
            "total": total,
        })

    futures_positions = [
        dict(row) for row in (snapshot.get("futures_positions", []) or [])
        if isinstance(row, Mapping)
    ]
    futures_accounts = [
        dict(row) for row in (snapshot.get("futures_account", []) or [])
        if isinstance(row, Mapping)
    ]
    return {
        "spot_assets": spot_assets,
        "spot_asset_count": len(spot_assets),
        "futures_positions": futures_positions,
        "open_futures_positions": len(futures_positions),
        "futures_accounts": futures_accounts,
        "fiat_valuation": None,
        "source": "Bitunix read-only API",
    }
