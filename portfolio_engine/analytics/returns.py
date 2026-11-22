"""Price-to-return transformations used by the portfolio engine."""
from __future__ import annotations
import numpy as np


def simple_returns(prices: object, periods: int = 1) -> np.ndarray:
    """Calculate arithmetic returns along time for 1D or (time, assets) prices."""
    if not isinstance(periods, (int, np.integer)) or isinstance(periods, bool) or periods < 1:
        raise ValueError("periods must be a positive integer")
    values = np.asarray(prices, dtype=float)
    if values.ndim not in (1, 2):
        raise ValueError("prices must be a 1D or 2D array")
    if values.shape[0] <= periods:
        raise ValueError("prices must contain more rows than periods")
    if not np.isfinite(values).all():
        raise ValueError("prices must contain only finite values")
    if (values <= 0).any():
        raise ValueError("prices must be strictly positive")
    return values[periods:] / values[:-periods] - 1.0
