"""Regularized expected-return model and as-of forecasting API."""
from __future__ import annotations
import numpy as np
from .dataset import build_supervised_dataset, validate_prices
from .features import technical_features


def _fit_ridge(features: np.ndarray, targets: np.ndarray, alpha: float) -> dict:
    if features.ndim != 2 or targets.shape != (features.shape[0],):
        raise ValueError("training feature/target dimensions do not match")
    if not np.isfinite(features).all() or not np.isfinite(targets).all():
        raise ValueError("training data must be finite")
    if not np.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be finite and positive")
    mean, scale = features.mean(axis=0), features.std(axis=0)
    scale[scale < 1e-12] = 1.0
    standardized = (features - mean) / scale
    design = np.column_stack([np.ones(features.shape[0]), standardized])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    try:
        coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    except np.linalg.LinAlgError as exc:
        raise ValueError("forecast model fit is singular") from exc
    return {"mean": mean, "scale": scale, "coefficients": coefficients,
            "residuals": targets - design @ coefficients}


def _predict(model: dict, feature_row: np.ndarray) -> float:
    standardized = (feature_row - model["mean"]) / model["scale"]
    return float(np.concatenate([[1.0], standardized]) @ model["coefficients"])


def forecast_at_index(prices: object, as_of_index: int, horizon: int = 7,
                      min_train_samples: int = 30, alpha: float = 10.0) -> dict:
    """Forecast at a historical origin using only labels matured by that origin."""
    values = validate_prices(prices)
    if as_of_index < 0 or as_of_index >= values.size:
        raise ValueError("as_of_index is outside the price series")
    if min_train_samples < 2:
        raise ValueError("min_train_samples must be at least 2")
    dataset = build_supervised_dataset(values[:as_of_index + 1], horizon=horizon)
    mature = dataset["target_indices"] <= as_of_index
    x_train, y_train = dataset["features"][mature], dataset["targets"][mature]
    if x_train.shape[0] < min_train_samples:
        raise ValueError("insufficient matured historical labels for forecasting")
    model = _fit_ridge(x_train, y_train, alpha)
    current_features = technical_features(values[:as_of_index + 1], as_of_index)
    prediction = _predict(model, current_features)
    residual_std = float(np.std(model["residuals"], ddof=1)) if y_train.size > 1 else None
    return {"forecast_return": prediction, "training_sample_count": int(y_train.size),
            "residual_std_in_sample": residual_std, "as_of_index": int(as_of_index),
            "horizon_days": int(horizon), "model": "standardized_ridge", "alpha": float(alpha)}


def forecast_latest(prices: object, horizon: int = 7, min_train_samples: int = 30,
                    min_validation_samples: int = 20, alpha: float = 10.0) -> dict:
    """Forecast latest close and calibrate uncertainty on matured walk-forward errors."""
    from .walk_forward import walk_forward_validate
    values = validate_prices(prices)
    forecast = forecast_at_index(values, values.size - 1, horizon, min_train_samples, alpha)
    validation = walk_forward_validate(values, horizon, min_train_samples, alpha)
    errors = np.asarray(validation["absolute_errors"], dtype=float)
    if errors.size >= min_validation_samples:
        error_q90 = float(np.quantile(errors, 0.90))
        lower, upper = forecast["forecast_return"] - error_q90, forecast["forecast_return"] + error_q90
        coverage, eligible = float(np.mean(errors <= error_q90)), True
    else:
        error_q90, lower, upper, coverage, eligible = None, None, None, None, False
    n_train, n_validation = forecast["training_sample_count"], int(errors.size)
    evidence = "high" if n_train >= 120 and n_validation >= 60 else (
        "moderate" if n_train >= 60 and n_validation >= min_validation_samples else "low")
    forecast.update({
        "lower_bound_90": lower, "upper_bound_90": upper,
        "walk_forward_validation_count": n_validation,
        "walk_forward_mae": validation["mae"],
        "walk_forward_directional_accuracy": validation["directional_accuracy"],
        "absolute_error_q90": error_q90, "historical_interval_coverage": coverage,
        "evidence_level": evidence, "view_eligible": bool(eligible and n_train >= min_train_samples),
        "uncertainty_method": "90th_percentile_absolute_walk_forward_error",
    })
    return forecast
