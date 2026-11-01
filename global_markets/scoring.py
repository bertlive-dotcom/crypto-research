"""Provider-agnostic candidate validation and opportunity scoring."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Mapping
from .config import DEFAULT_SCORE_WEIGHTS, MIN_SCORE_COVERAGE

def _parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("observed_at must be an ISO timestamp or datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def rank_candidate(candidate: Mapping, weights: Mapping[str, float] | None = None,
                   min_coverage: float = MIN_SCORE_COVERAGE,
                   max_age_seconds: int | None = None, now: datetime | None = None) -> dict:
    """Validate and score normalized candidate data without fetching market data.

    Component scores are numeric values from 0 to 100. Missing components are
    omitted and remaining weights normalized. A score is withheld below the
    minimum weight coverage. Higher risk_control means lower/better-controlled risk.
    """
    weights = dict(weights or DEFAULT_SCORE_WEIGHTS)
    if not weights or any(not isinstance(v, (int, float)) or v < 0 for v in weights.values()):
        raise ValueError("weights must contain non-negative numeric values")
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("at least one weight must be greater than zero")
    if not 0 <= min_coverage <= 1:
        raise ValueError("min_coverage must be between 0 and 1")

    reasons = []
    asset_class = str(candidate.get("asset_class", "")).lower()
    if not candidate.get("symbol"): reasons.append("missing_symbol")
    if not candidate.get("asset_id"): reasons.append("missing_asset_id")
    if asset_class not in {"equity", "etf", "index", "crypto", "forex", "commodity", "future"}:
        reasons.append("unsupported_asset_class")
    try:
        price = float(candidate.get("price"))
        if price <= 0: reasons.append("invalid_price")
    except (TypeError, ValueError):
        reasons.append("missing_or_invalid_price")

    age_seconds = None
    observed_at = candidate.get("observed_at")
    if not observed_at:
        reasons.append("missing_observed_at")
    else:
        try:
            current = _parse_timestamp(now or datetime.now(timezone.utc))
            age_seconds = max(0.0, (current - _parse_timestamp(observed_at)).total_seconds())
            if max_age_seconds is not None and age_seconds > max_age_seconds:
                reasons.append("stale_market_data")
        except (TypeError, ValueError, OverflowError):
            reasons.append("invalid_observed_at")

    if reasons:
        return {"eligible": False, "score": None, "coverage": 0.0,
                "component_scores": {}, "reasons": reasons, "age_seconds": age_seconds}

    supplied = candidate.get("scores") or {}
    valid_scores, available_weight = {}, 0.0
    for component, weight in weights.items():
        value = supplied.get(component)
        if value is None: continue
        try: score_value = float(value)
        except (TypeError, ValueError): continue
        if 0 <= score_value <= 100 and weight > 0:
            valid_scores[component] = score_value
            available_weight += weight

    coverage = available_weight / total_weight
    if coverage < min_coverage:
        reasons.append("insufficient_score_coverage")
        score = None
    else:
        score = round(sum(valid_scores[k] * weights[k] for k in valid_scores) / available_weight, 2)
    return {"eligible": score is not None, "score": score, "coverage": round(coverage, 4),
            "component_scores": valid_scores, "reasons": reasons,
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None}