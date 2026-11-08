"""Read-only prediction-market intelligence primitives."""

from .polymarket import PolymarketClient, PolymarketDataError
from .scoring import probability_divergence, classify_market_category, calibration_metrics

__all__ = [
    "PolymarketClient",
    "PolymarketDataError",
    "probability_divergence",
    "classify_market_category",
    "calibration_metrics",
]
