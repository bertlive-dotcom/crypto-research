"""Black-Litterman posterior expected-return calculation."""
from __future__ import annotations
import numpy as np


def posterior_expected_returns(
    covariance: object,
    prior_returns: object,
    pick_matrix: object,
    view_returns: object,
    view_covariance: object,
    tau: float = 0.05,
) -> np.ndarray:
    """Combine prior returns and investor views without explicit matrix inverses.

    Uses Pi + tau*Sigma*P.T @ solve(P*tau*Sigma*P.T + Omega, Q - P*Pi).
    Inputs and output must use consistent return horizons and units.
    """
    sigma = np.asarray(covariance, dtype=float)
    pi = np.asarray(prior_returns, dtype=float)
    p = np.asarray(pick_matrix, dtype=float)
    q = np.asarray(view_returns, dtype=float)
    omega = np.asarray(view_covariance, dtype=float)
    if sigma.ndim != 2 or sigma.shape[0] != sigma.shape[1]:
        raise ValueError("covariance must be a square matrix")
    n_assets = sigma.shape[0]
    if pi.shape != (n_assets,):
        raise ValueError("prior_returns length must match covariance dimensions")
    if p.ndim != 2 or p.shape[1] != n_assets:
        raise ValueError("pick_matrix must have shape (n_views, n_assets)")
    n_views = p.shape[0]
    if q.shape != (n_views,):
        raise ValueError("view_returns length must match number of views")
    if omega.shape != (n_views, n_views):
        raise ValueError("view_covariance must have shape (n_views, n_views)")
    if not all(np.isfinite(x).all() for x in (sigma, pi, p, q, omega)):
        raise ValueError("all inputs must contain only finite values")
    if not np.isfinite(tau) or tau <= 0:
        raise ValueError("tau must be finite and positive")
    if not np.allclose(sigma, sigma.T, atol=1e-10):
        raise ValueError("covariance must be symmetric")
    try:
        np.linalg.cholesky(sigma)
    except np.linalg.LinAlgError as exc:
        raise ValueError("covariance must be positive definite") from exc
    if n_views == 0:
        return pi.copy()
    if not np.allclose(omega, omega.T, atol=1e-10):
        raise ValueError("view_covariance must be symmetric")
    try:
        np.linalg.cholesky(omega)
    except np.linalg.LinAlgError as exc:
        raise ValueError("view_covariance must be positive definite") from exc
    scaled_sigma = tau * sigma
    view_system = p @ scaled_sigma @ p.T + omega
    innovation = q - p @ pi
    try:
        posterior = pi + scaled_sigma @ p.T @ np.linalg.solve(view_system, innovation)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Black-Litterman view system is singular") from exc
    if not np.isfinite(posterior).all():
        raise ValueError("posterior returns are not finite")
    return posterior
