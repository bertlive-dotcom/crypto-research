"""Research-only horizon suite for causal forecast model comparisons."""
from __future__ import annotations

import numpy as np

from .dataset import validate_prices, _validate_benchmark
from .walk_forward import walk_forward_validate


DEFAULT_HORIZONS = (3, 7, 14, 30)
_MODEL_NAMES = (
    "ridge", "zero_return", "simple_momentum", "mean_reversion",
    "random_forest", "gradient_boosting",
)


def build_model_comparison_report(
    prices: object,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_train_samples: int = 30,
    alpha: float = 10.0,
    benchmark_prices: object | None = None,
) -> dict:
    """Report fixed-model metrics for requested horizons on one price series.

    Tree ensembles are loaded lazily from the optional research dependency.
    If it is absent, their rows are explicitly marked unavailable while the
    Ridge and three deterministic baselines remain usable.
    """
    values = validate_prices(prices)
    benchmark = _validate_benchmark(benchmark_prices, values.size)
    if not isinstance(horizons, (tuple, list)) or not horizons:
        raise ValueError("horizons must be a non-empty tuple or list")
    normalized_horizons = []
    for horizon in horizons:
        if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon < 1:
            raise ValueError("each horizon must be a positive integer")
        normalized_horizons.append(int(horizon))
    if len(set(normalized_horizons)) != len(normalized_horizons):
        raise ValueError("horizons must be unique")

    results = {}
    for horizon in normalized_horizons:
        validation = walk_forward_validate(
            values, horizon=horizon, min_train_samples=min_train_samples,
            alpha=alpha, benchmark_prices=benchmark, include_tree_models=True,
        )
        results[str(horizon)] = {
            "horizon_days": horizon,
            "validation_count": validation["validation_count"],
            "fold_step_days": validation["fold_step_days"],
            "minimum_training_samples": validation["minimum_training_samples"],
            "purge_rule": validation["purge_rule"],
            "models": {name: validation["model_metrics"][name] for name in _MODEL_NAMES},
        }

    tree_status = "available" if all(
        results[str(horizon)]["models"][name]["available"]
        for horizon in normalized_horizons
        for name in ("random_forest", "gradient_boosting")
    ) else "unavailable_optional_dependency"
    limitations = [
        "Validation return windows are non-overlapping, but adjacent origins still share a price close at the fold boundary.",
        "Training labels overlap one another; every training label must nevertheless have matured by its validation origin.",
        "Tree models use fixed settings without hyperparameter search, so this is a candidate comparison rather than model selection.",
        "Comparing multiple models across four horizons creates multiple-comparison risk; no statistical correction is applied.",
        "Scores do not include fees, slippage, liquidity constraints, taxes, or portfolio-level effects.",
        "Directional accuracy weights small and large moves equally and does not use a neutral prediction threshold.",
        "Results from one historical price series do not establish stable future performance; the number of independent folds falls as the horizon grows.",
    ]
    if tree_status != "available":
        limitations.append(
            "Random Forest and Gradient Boosting metrics are unavailable until the optional scikit-learn research requirements are installed."
        )
    return {
        "status": "research_only",
        "validation_protocol": "expanding_non_overlapping_purged_walk_forward",
        "horizons_days": normalized_horizons,
        "history_observations": int(values.size),
        "minimum_training_samples": int(min_train_samples),
        "target_definition": "close[t+horizon_days] / close[t] - 1",
        "metric_definitions": {
            "mae": "mean absolute error of the horizon return forecast",
            "rmse": "root mean squared error of the horizon return forecast",
            "directional_accuracy": "share of non-neutral forecast folds where predicted and realized return signs match",
            "directional_coverage": "share of folds with a non-zero directional forecast",
            "mean_error": "mean(prediction - actual); positive values indicate over-forecasting",
            "mae_skill_vs_zero": "1 - model MAE / zero-return baseline MAE; positive values beat zero-return",
        },
        "fixed_tree_model_settings": {
            "random_forest": {
                "estimators": 50, "max_depth": 3, "max_features": 1.0,
                "minimum_leaf_samples": "max(2, min(5, min_train_samples // 10))",
                "random_state": 1729,
            },
            "gradient_boosting": {
                "estimators": 50, "learning_rate": 0.03, "max_depth": 1,
                "loss": "huber",
                "minimum_leaf_samples": "max(2, min(5, min_train_samples // 10))",
                "random_state": 1729,
            },
        },
        "tree_models_status": tree_status,
        "results": results,
        "limitations": limitations,
        "eligibility_policy": "unchanged; this comparison report does not qualify portfolio views",
        "read_only": True,
    }
