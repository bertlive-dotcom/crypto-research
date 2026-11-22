"""Long-only, capped-weight optimizer for Black-Litterman posterior returns."""
from __future__ import annotations
import numpy as np


def _project_capped_simplex(values: np.ndarray, cap: float) -> np.ndarray:
    """Euclidean projection onto {w: sum(w)=1, 0<=w<=cap}."""
    if values.ndim != 1 or values.size == 0:
        raise ValueError("values must be a non-empty vector")
    if not np.isfinite(values).all() or not 0.0 < cap <= 1.0:
        raise ValueError("projection inputs are invalid")
    if values.size * cap < 1.0 - 1e-12:
        raise ValueError("max_weight is too small for the number of assets")
    low = float(np.min(values - cap))
    high = float(np.max(values))
    for _ in range(100):
        midpoint = (low + high) * 0.5
        projected = np.clip(values - midpoint, 0.0, cap)
        if projected.sum() > 1.0:
            low = midpoint
        else:
            high = midpoint
    result = np.clip(values - (low + high) * 0.5, 0.0, cap)
    # Correct only floating-point residual while respecting the cap.
    residual = 1.0 - float(result.sum())
    for index in np.argsort(-result if residual > 0 else result):
        if abs(residual) <= 1e-12:
            break
        room = cap - result[index] if residual > 0 else result[index]
        adjustment = np.sign(residual) * min(abs(residual), room)
        result[index] += adjustment
        residual -= adjustment
    if abs(float(result.sum()) - 1.0) > 1e-9:
        raise ValueError("capped simplex projection did not converge")
    return result


def optimize_long_only(
    expected_returns: object, covariance: object, *, risk_aversion: float = 2.5,
    max_weight: float = 0.35, max_iterations: int = 5000, tolerance: float = 1e-10,
) -> dict:
    """Maximize mu'w - delta/2*w'Sigma*w under long-only and max-weight constraints."""
    mu = np.asarray(expected_returns, dtype=float)
    sigma = np.asarray(covariance, dtype=float)
    if mu.ndim != 1 or mu.size == 0 or sigma.shape != (mu.size, mu.size):
        raise ValueError("expected returns and covariance dimensions do not match")
    if not np.isfinite(mu).all() or not np.isfinite(sigma).all():
        raise ValueError("optimizer inputs must be finite")
    if not np.allclose(sigma, sigma.T, atol=1e-10):
        raise ValueError("covariance must be symmetric")
    if not np.isfinite(risk_aversion) or risk_aversion <= 0:
        raise ValueError("risk_aversion must be finite and positive")
    if not isinstance(max_iterations, int) or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    try:
        np.linalg.cholesky(sigma)
    except np.linalg.LinAlgError as exc:
        raise ValueError("covariance must be positive definite") from exc
    largest_eigenvalue = float(np.linalg.eigvalsh(sigma).max())
    step = 1.0 / (risk_aversion * largest_eigenvalue)
    weights = np.full(mu.size, 1.0 / mu.size)
    weights = _project_capped_simplex(weights, max_weight)
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        gradient = mu - risk_aversion * (sigma @ weights)
        updated = _project_capped_simplex(weights + step * gradient, max_weight)
        if float(np.linalg.norm(updated - weights, ord=2)) <= tolerance:
            weights = updated
            break
        weights = updated
    expected = float(mu @ weights)
    variance = float(weights @ sigma @ weights)
    return {
        "weights": weights, "expected_return": expected,
        "volatility": float(np.sqrt(max(variance, 0.0))),
        "variance": variance, "objective": expected - 0.5 * risk_aversion * variance,
        "iterations": iterations, "converged": iterations < max_iterations,
        "max_weight": float(max_weight), "risk_aversion": float(risk_aversion),
    }
