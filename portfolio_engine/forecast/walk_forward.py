"""Purged, non-overlapping expanding-window forecast validation."""
from __future__ import annotations

import numpy as np

from .dataset import build_supervised_dataset, validate_prices, _validate_benchmark
from .features import MIN_FEATURE_HISTORY, technical_features
from .model import _fit_ridge, _predict


_TREE_MODEL_NAMES = ("random_forest", "gradient_boosting")


def _tree_estimators(min_train_samples: int) -> dict:
    """Return fixed, conservative optional estimators without tuning on OOS data."""
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    except ImportError:
        return {}

    min_leaf = max(2, min(5, min_train_samples // 10))
    return {
        "random_forest": lambda: RandomForestRegressor(
            n_estimators=50, max_depth=3, min_samples_leaf=min_leaf,
            max_features=1.0, random_state=1729, n_jobs=1,
        ),
        "gradient_boosting": lambda: GradientBoostingRegressor(
            n_estimators=50, learning_rate=0.03, max_depth=1,
            min_samples_leaf=min_leaf, loss="huber", random_state=1729,
        ),
    }


def _model_metrics(actuals: np.ndarray, predictions: np.ndarray,
                   zero_baseline_mae: float) -> dict:
    if actuals.size == 0:
        return {"available": True, "validation_count": 0, "mae": None, "rmse": None,
                "directional_accuracy": None, "directional_count": 0,
                "directional_coverage": 0.0, "mean_error": None,
                "mae_skill_vs_zero": None}
    errors = predictions - actuals
    mae = float(np.mean(np.abs(errors)))
    directional = (predictions != 0.0) & (actuals != 0.0)
    return {
        "available": True,
        "validation_count": int(actuals.size),
        "mae": mae,
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "directional_accuracy": (
            float(np.mean(np.sign(predictions[directional]) == np.sign(actuals[directional])))
            if directional.any() else None
        ),
        "directional_count": int(directional.sum()),
        "directional_coverage": float(np.mean(predictions != 0.0)),
        "mean_error": float(np.mean(errors)),
        "mae_skill_vs_zero": (
            float(1.0 - mae / zero_baseline_mae) if zero_baseline_mae > 0 else None
        ),
    }


def walk_forward_validate(prices: object, horizon: int = 7,
                          min_train_samples: int = 30, alpha: float = 10.0,
                          benchmark_prices: object | None = None,
                          include_tree_models: bool = False) -> dict:
    """Evaluate fixed models at horizon-spaced origins with mature labels only.

    At each origin, training labels are purged unless their endpoint is at or
    before that origin. Evaluation origins advance by exactly ``horizon`` days,
    so their forward-return windows do not overlap. Tree ensembles are optional
    and are never used by the forecast-eligibility gate.
    """
    if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if not isinstance(min_train_samples, (int, np.integer)) or isinstance(min_train_samples, bool) or min_train_samples < 2:
        raise ValueError("min_train_samples must be an integer of at least 2")
    if not isinstance(include_tree_models, bool):
        raise ValueError("include_tree_models must be a boolean")
    values = validate_prices(prices)
    benchmark = _validate_benchmark(benchmark_prices, values.size)
    dataset = build_supervised_dataset(values, horizon=horizon, benchmark_prices=benchmark)
    targets, target_indices = dataset["targets"], dataset["target_indices"]

    model_predictions = {
        "ridge": [], "zero_return": [], "simple_momentum": [], "mean_reversion": [],
    }
    tree_factories = _tree_estimators(int(min_train_samples)) if include_tree_models else {}
    for name in _TREE_MODEL_NAMES:
        model_predictions[name] = []
    folds, actuals, origins, evaluation_ends = [], [], [], []

    # By this first origin, at least min_train_samples labels have closed.
    first_origin = MIN_FEATURE_HISTORY - 1 + int(min_train_samples) + int(horizon)
    for origin in range(first_origin, values.size - int(horizon), int(horizon)):
        matured = target_indices <= origin
        x_train, y_train = dataset["features"][matured], targets[matured]
        if y_train.size < min_train_samples:
            continue
        benchmark_prefix = benchmark[:origin + 1] if benchmark is not None else None
        feature_row = technical_features(values[:origin + 1], origin, benchmark_prefix)
        ridge = _fit_ridge(x_train, y_train, 10.0 if alpha is None else alpha)

        model_predictions["ridge"].append(_predict(ridge, feature_row))
        model_predictions["zero_return"].append(0.0)
        trailing_return = float(values[origin] / values[origin - int(horizon)] - 1.0)
        model_predictions["simple_momentum"].append(trailing_return)
        model_predictions["mean_reversion"].append(-trailing_return)

        for name in _TREE_MODEL_NAMES:
            factory = tree_factories.get(name)
            if factory is not None:
                estimator = factory()
                estimator.fit(x_train, y_train)
                model_predictions[name].append(float(estimator.predict(feature_row.reshape(1, -1))[0]))

        actual = float(values[origin + int(horizon)] / values[origin] - 1.0)
        actuals.append(actual)
        origins.append(int(origin))
        evaluation_ends.append(int(origin + int(horizon)))
        folds.append({
            "origin_index": int(origin),
            "evaluation_end_index": int(origin + int(horizon)),
            "training_sample_count": int(y_train.size),
            "max_training_target_index": int(target_indices[matured].max()),
        })

    realized = np.asarray(actuals, dtype=float)
    zero_baseline_mae = float(np.mean(np.abs(realized))) if realized.size else None
    model_metrics = {}
    for name, values_for_model in model_predictions.items():
        if name in _TREE_MODEL_NAMES and name not in tree_factories:
            model_metrics[name] = {
                "available": False,
                "reason": "not_requested" if not include_tree_models else "optional_dependency_unavailable",
                "dependency": "scikit-learn",
                "validation_count": 0,
                "mae": None, "rmse": None, "directional_accuracy": None,
                "directional_count": 0, "directional_coverage": None,
                "mean_error": None, "mae_skill_vs_zero": None,
            }
            continue
        predictions = np.asarray(values_for_model, dtype=float)
        model_metrics[name] = _model_metrics(realized, predictions, zero_baseline_mae or 0.0)

    ridge_metrics = model_metrics["ridge"]
    return {
        "predictions": model_predictions["ridge"],
        "model_predictions": model_predictions,
        "model_metrics": model_metrics,
        "actuals": realized.tolist(),
        "absolute_errors": np.abs(realized - np.asarray(model_predictions["ridge"], dtype=float)).tolist(),
        "origins": origins,
        "evaluation_end_indices": evaluation_ends,
        "folds": folds,
        "mae": ridge_metrics["mae"],
        "rmse": ridge_metrics["rmse"],
        "zero_baseline_mae": zero_baseline_mae,
        "mae_skill_vs_zero": ridge_metrics["mae_skill_vs_zero"],
        "directional_accuracy": ridge_metrics["directional_accuracy"],
        "validation_count": int(realized.size),
        "horizon_days": int(horizon),
        "fold_step_days": int(horizon),
        "minimum_training_samples": int(min_train_samples),
        "purge_rule": "training_label_target_index_at_or_before_validation_origin",
        "validation_protocol": "expanding_non_overlapping_purged_walk_forward",
    }
