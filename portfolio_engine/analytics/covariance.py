"""Robust sample covariance estimation with diagonal shrinkage."""
from __future__ import annotations
import numpy as np


def estimate_covariance(
    returns: object,
    shrinkage: float = 0.20,
    annualization: float = 1.0,
    eigenvalue_floor: float = 1e-12,
) -> np.ndarray:
    """Estimate symmetric positive-definite covariance with diagonal shrinkage.

    A shrinkage of 0.20 retains 80% sample covariance and shrinks 20% toward
    its diagonal target. Set annualization=7 for a seven-day covariance.
    """
    values = np.asarray(returns, dtype=float)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if values.ndim != 2:
        raise ValueError("returns must be a 1D or 2D array")
    if values.shape[0] < 2 or values.shape[1] < 1:
        raise ValueError("at least two observations and one asset are required")
    if not np.isfinite(values).all():
        raise ValueError("returns must contain only finite values")
    if not np.isfinite(shrinkage) or not 0.0 <= shrinkage <= 1.0:
        raise ValueError("shrinkage must be between 0 and 1")
    if not np.isfinite(annualization) or annualization <= 0:
        raise ValueError("annualization must be finite and positive")
    if not np.isfinite(eigenvalue_floor) or eigenvalue_floor <= 0:
        raise ValueError("eigenvalue_floor must be finite and positive")

    sample = np.atleast_2d(np.cov(values, rowvar=False, ddof=1))
    target = np.diag(np.diag(sample))
    shrunk = (1.0 - shrinkage) * sample + shrinkage * target
    shrunk = (shrunk + shrunk.T) * 0.5
    eigenvalues, eigenvectors = np.linalg.eigh(shrunk)
    scale = max(float(np.max(np.abs(eigenvalues))), 1.0)
    floor = max(eigenvalue_floor, scale * 1e-12)
    eigenvalues = np.maximum(eigenvalues, floor)
    positive_definite = (eigenvectors * eigenvalues) @ eigenvectors.T
    result = (positive_definite + positive_definite.T) * (0.5 * annualization)
    np.linalg.cholesky(result)
    return result
