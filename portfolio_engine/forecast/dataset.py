"""Supervised forward-return dataset with explicit origin and label timestamps."""
from __future__ import annotations
import numpy as np
from .features import FEATURE_NAMES, MIN_FEATURE_HISTORY, technical_features


def validate_prices(prices: object) -> np.ndarray:
    values = np.asarray(prices, dtype=float)
    if values.ndim != 1 or values.size < MIN_FEATURE_HISTORY:
        raise ValueError(f"prices must be a 1D series with at least {MIN_FEATURE_HISTORY} observations")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("prices must be finite and strictly positive")
    return values


def build_supervised_dataset(prices: object, horizon: int = 7) -> dict:
    """Build features at t and labels close[t+h]/close[t]-1 with explicit maturity indices."""
    values = validate_prices(prices)
    if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    origins = np.arange(MIN_FEATURE_HISTORY - 1, values.size - horizon)
    if origins.size == 0:
        raise ValueError("insufficient observations for requested horizon")
    features = np.vstack([technical_features(values, int(i)) for i in origins])
    return {
        "features": features,
        "targets": values[origins + horizon] / values[origins] - 1.0,
        "origin_indices": origins,
        "target_indices": origins + horizon,
        "feature_names": FEATURE_NAMES,
        "horizon_days": int(horizon),
    }
