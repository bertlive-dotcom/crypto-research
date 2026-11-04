"""Six-stage deterministic agent pipeline for the existing paper-trading scanner.

These are auditable software roles, not autonomous LLM agents. The pipeline
never places live orders and delegates final eligibility/risk constraints to
the existing Market Scanner rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import MAX_OPEN_POSITIONS
from .market_scanner import apply_paper_rules


AGENT_NAMES = ("SCOUT", "FILTER", "ANALYST", "RISK_MANAGER", "EXECUTOR", "LOGGER")


def _valid_candidate(row: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(row, dict):
        return False, "Candidate is not a dictionary."
    if not str(row.get("symbol") or "").strip():
        return False, "Missing exchange symbol."
    if not str(row.get("base_asset") or "").strip():
        return False, "Missing base asset."
    try:
        price = float(row.get("price_usdt"))
    except (TypeError, ValueError):
        return False, "Invalid price."
    if price <= 0:
        return False, "Price must be positive."
    features = row.get("features")
    if not isinstance(features, dict) or not isinstance(features.get("1h"), dict):
        return False, "Missing 1h feature record."
    if features["1h"].get("candle_close_time") is None:
        return False, "Missing closed-candle timestamp."
    return True, "Candidate identity, price and closed-candle metadata valid."


def run_agent_pipeline(candidates: list[dict], portfolio: dict, mode: str = "paper") -> dict:
    """Run the six auditable stages and return only risk-approved paper candidates.

    The mode gate is fail-closed: anything except the literal 'paper' blocks
    execution. Existing scanner rules remain the authority for entry eligibility,
    daily loss limits, open positions and duplicate-asset prevention.
    """
    observed_at = datetime.now(timezone.utc).isoformat()
    audit: list[dict[str, Any]] = []
    scouted: list[dict] = []

    # 1. SCOUT — validate that the scanner supplied a usable candidate record.
    for row in candidates:
        valid, detail = _valid_candidate(row)
        audit.append({
            "symbol": row.get("symbol", "UNKNOWN") if isinstance(row, dict) else "UNKNOWN",
            "agent": "SCOUT", "status": "PASS" if valid else "REJECTED",
            "detail": detail,
        })
        if valid:
            scouted.append(row)

    # 2. FILTER — enforce the scanner's hard gates and minimum auto-entry score.
    filtered: list[dict] = []
    for row in scouted:
        eligible = bool(row.get("auto_entry_eligible")) and bool(row.get("hard_checks_pass"))
        detail = "Hard gates and auto-entry score passed." if eligible else (
            "; ".join(row.get("hard_gate_failures") or row.get("reasons") or [])
            or "Candidate did not meet auto-entry eligibility."
        )
        audit.append({
            "symbol": row["symbol"], "agent": "FILTER",
            "status": "PASS" if eligible else "REJECTED", "detail": detail,
        })
        if eligible:
            filtered.append(row)

    # 3. ANALYST — record a compact, explainable readout; it does not override gates.
    for row in filtered:
        features = row.get("features") or {}
        one_hour = features.get("1h") or {}
        audit.append({
            "symbol": row["symbol"], "agent": "ANALYST", "status": "REVIEWED",
            "detail": (
                f"Score {row.get('score', 0)}; 1h RSI={one_hour.get('rsi14')}; "
                f"MACD histogram={one_hour.get('macd_hist')}; "
                f"relative volume={one_hour.get('volume_ratio')}; "
                "descriptive technical inputs only, not a return forecast."
            ),
        })

    # 4. RISK_MANAGER — existing rules are the single source of truth.
    risk_approved = apply_paper_rules(filtered, portfolio)
    approved_symbols = {row["symbol"] for row in risk_approved}
    for row in filtered:
        passed = row["symbol"] in approved_symbols
        audit.append({
            "symbol": row["symbol"], "agent": "RISK_MANAGER",
            "status": "PASS" if passed else "BLOCKED",
            "detail": (
                "Existing portfolio rules approved this paper entry."
                if passed else
                f"Blocked by existing portfolio controls (max open positions: {MAX_OPEN_POSITIONS}, "
                "daily loss limit, or duplicate/open asset rule)."
            ),
        })

    # 5. EXECUTOR — this stage only authorizes the existing paper_entry function.
    executor_enabled = mode == "paper"
    executable = risk_approved if executor_enabled else []
    for row in risk_approved:
        audit.append({
            "symbol": row["symbol"], "agent": "EXECUTOR",
            "status": "AUTHORIZED_PAPER" if executor_enabled else "BLOCKED_MODE",
            "detail": (
                "Authorized for existing simulated paper_entry only; no exchange API."
                if executor_enabled else
                "Execution blocked: pipeline mode is not explicitly 'paper'."
            ),
        })

    # 6. LOGGER — append a cycle-level record and expose auditable per-stage events.
    audit.append({
        "symbol": "*", "agent": "LOGGER", "status": "RECORDED",
        "detail": (
            f"Observed {len(candidates)} candidates; {len(scouted)} passed Scout; "
            f"{len(filtered)} passed Filter; {len(executable)} authorized for paper execution."
        ),
    })
    return {
        "mode": mode,
        "observed_at": observed_at,
        "agents": list(AGENT_NAMES),
        "candidate_count": len(candidates),
        "scouted_count": len(scouted),
        "filtered_count": len(filtered),
        "risk_approved_count": len(risk_approved),
        "authorized_count": len(executable),
        "audit": audit,
        "approved_candidates": executable,
    }
