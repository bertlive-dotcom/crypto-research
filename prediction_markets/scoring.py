"""Conservative analytics for prediction-market observations.

These functions describe market-implied probabilities. They do not generate
trade instructions or treat crowd prices as calibrated real-world odds.
"""

from __future__ import annotations

from typing import Optional


def probability_divergence(
    market_probability: Optional[float],
    reference_probability: Optional[float],
    threshold_pp: float = 5.0,
) -> dict:
    """Compare an exchange-implied probability with an independent estimate.

    The gap is expressed in percentage points (market minus reference).
    No divergence is emitted if either input is absent or invalid.
    """
    if threshold_pp < 0:
        raise ValueError("threshold_pp must be non-negative")

    values = (market_probability, reference_probability)
    if any(value is None for value in values):
        return {
            "available": False,
            "gap_pp": None,
            "direction": "unavailable",
            "material": False,
        }

    market = float(market_probability)
    reference = float(reference_probability)
    if not (0.0 <= market <= 1.0 and 0.0 <= reference <= 1.0):
        raise ValueError("probabilities must be between 0 and 1")

    gap_pp = (market - reference) * 100.0
    if gap_pp > 0:
        direction = "market_higher"
    elif gap_pp < 0:
        direction = "market_lower"
    else:
        direction = "aligned"

    return {
        "available": True,
        "gap_pp": round(gap_pp, 2),
        "direction": direction,
        "material": abs(gap_pp) >= threshold_pp,
    }


def classify_market_category(question: str, tags=None) -> str:
    """Classify a market into crypto, macro, or other using transparent rules."""
    text = str(question or "").lower()
    tag_text = " ".join(
        str(tag.get("label", tag.get("name", ""))) if isinstance(tag, dict) else str(tag)
        for tag in (tags or [])
    ).lower()
    text = f"{text} {tag_text}"

    crypto_terms = (
        "bitcoin", "btc", "ethereum", "ether", "eth", "solana", "sol ",
        "crypto", "token", "altcoin", "xrp", "dogecoin", "doge",
    )
    macro_terms = (
        "federal reserve", "fed ", "fomc", "interest rate", "rate cut",
        "rate hike", "inflation", "cpi", "pce", "recession", "gdp",
        "unemployment", "treasury", "yield",
    )
    if any(term in text for term in crypto_terms):
        return "crypto"
    if any(term in text for term in macro_terms):
        return "macro"
    return "other"



def calibration_metrics(predictions, outcomes, epsilon: float = 1e-6) -> dict:
    """Return proper scoring rules for resolved binary forecasts.

    Predictions are probabilities in [0, 1], outcomes are binary 0/1 values.
    This is descriptive validation; it does not imply predictive skill.
    """
    if not 0 < epsilon < 0.5:
        raise ValueError("epsilon must be between 0 and 0.5")
    if len(predictions) != len(outcomes):
        raise ValueError("predictions and outcomes must have equal length")
    if not predictions:
        return {
            "sample_size": 0,
            "brier_score": None,
            "log_loss": None,
            "mean_probability": None,
            "observed_frequency": None,
        }

    probabilities = [float(value) for value in predictions]
    labels = [float(value) for value in outcomes]
    if any(not 0 <= value <= 1 for value in probabilities):
        raise ValueError("predictions must be between 0 and 1")
    if any(value not in (0.0, 1.0) for value in labels):
        raise ValueError("outcomes must be binary 0 or 1")

    count = len(probabilities)
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / count
    clipped = [min(1.0 - epsilon, max(epsilon, p)) for p in probabilities]
    log_loss = -sum(
        y * __import__("math").log(p) + (1.0 - y) * __import__("math").log(1.0 - p)
        for p, y in zip(clipped, labels)
    ) / count
    return {
        "sample_size": count,
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "mean_probability": round(sum(probabilities) / count, 6),
        "observed_frequency": round(sum(labels) / count, 6),
    }
