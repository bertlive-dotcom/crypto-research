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
