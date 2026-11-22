"""Market-cap equilibrium weights and implied Black-Litterman returns."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
import numpy as np


def market_cap_weights(
    market_caps: Mapping[str, float] | Sequence[float],
    asset_order: Sequence[str] | None = None,
) -> np.ndarray:
    """Normalize positive market caps; missing or invalid caps fail closed."""
    if isinstance(market_caps, Mapping):
        names = list(market_caps.keys()) if asset_order is None else list(asset_order)
        missing = [name for name in names if name not in market_caps]
        if missing:
            raise ValueError(f"missing market caps for assets: {missing}")
        values = np.asarray([market_caps[name] for name in names], dtype=float)
    else:
        values = np.asarray(market_caps, dtype=float)
        if values.ndim != 1:
            raise ValueError("market_caps must be a 1D sequence")
        if asset_order is not None and len(asset_order) != values.size:
            raise ValueError("asset_order length must match market_caps")
    if values.ndim != 1 or values.size == 0:
        raise ValueError("at least one market cap is required")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("market caps must be finite and strictly positive")
    total = float(values.sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("market cap total must be finite and positive")
    return values / total


def market_equilibrium_returns(
    covariance: object, weights: object, risk_aversion: float = 2.5
) -> np.ndarray:
    """Calculate implied equilibrium returns: Pi = delta * Sigma * w."""
    sigma = np.asarray(covariance, dtype=float)
    w = np.asarray(weights, dtype=float)
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1]:
        raise ValueError("covariance must be a square matrix")
    if w.ndim != 1 or w.size != sigma.shape[0]:
        raise ValueError("weights length must match covariance dimensions")
    if not np.isfinite(sigma).all() or not np.isfinite(w).all():
        raise ValueError("covariance and weights must be finite")
    if not np.allclose(sigma, sigma.T, atol=1e-10):
        raise ValueError("covariance must be symmetric")
    if np.any(w < 0) or not np.isclose(w.sum(), 1.0, atol=1e-8):
        raise ValueError("weights must be non-negative and sum to one")
    if not np.isfinite(risk_aversion) or risk_aversion <= 0:
        raise ValueError("risk_aversion must be finite and positive")
    try:
        np.linalg.cholesky(sigma)
    except np.linalg.LinAlgError as exc:
        raise ValueError("covariance must be positive definite") from exc
    return float(risk_aversion) * (sigma @ w)
