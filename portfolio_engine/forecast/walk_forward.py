"""Expanding-window validation with strictly matured training labels."""
from __future__ import annotations
import numpy as np
from .dataset import build_supervised_dataset, validate_prices
from .features import MIN_FEATURE_HISTORY, technical_features
from .model import _fit_ridge, _predict


def walk_forward_validate(prices: object, horizon: int = 7,
                          min_train_samples: int = 30, alpha: float = 10.0) -> dict:
    """Predict eligible origins using only training labels ending by each origin."""
    values = validate_prices(prices)
    if min_train_samples < 2:
        raise ValueError("min_train_samples must be at least 2")
    dataset = build_supervised_dataset(values, horizon=horizon)
    targets, target_indices = dataset["targets"], dataset["target_indices"]
    predictions, actuals, origins = [], [], []
    first_origin = MIN_FEATURE_HISTORY - 1 + min_train_samples + horizon
    for origin in range(first_origin, values.size - horizon):
        mature = target_indices <= origin
        x_train, y_train = dataset["features"][mature], targets[mature]
        if y_train.size < min_train_samples:
            continue
        model = _fit_ridge(x_train, y_train, alpha)
        row = technical_features(values[:origin + 1], origin)
        predictions.append(_predict(model, row))
        actuals.append(float(values[origin + horizon] / values[origin] - 1.0))
        origins.append(origin)
    if not predictions:
        return {"predictions": [], "actuals": [], "absolute_errors": [], "origins": [],
                "mae": None, "zero_baseline_mae": None, "mae_skill_vs_zero": None,
                "directional_accuracy": None, "validation_count": 0, "horizon_days": int(horizon)}
    predicted, realized = np.asarray(predictions), np.asarray(actuals)
    errors = np.abs(realized - predicted)
    mae = float(errors.mean())
    baseline_mae = float(np.abs(realized).mean())
    skill = 1.0 - mae / baseline_mae if baseline_mae > 0 else None
    return {"predictions": predicted.tolist(), "actuals": realized.tolist(),
            "absolute_errors": errors.tolist(), "origins": origins,
            "mae": mae, "zero_baseline_mae": baseline_mae, "mae_skill_vs_zero": skill,
            "directional_accuracy": float(np.mean(np.sign(predicted) == np.sign(realized))),
            "validation_count": int(errors.size), "horizon_days": int(horizon)}
