"""Local research helpers for frozen, forward-only forecast observation."""
from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path
import tempfile

import numpy as np

from .dataset import build_supervised_dataset, validate_prices, _validate_benchmark
from .features import technical_features
from .model import _fit_ridge, _predict
from .walk_forward import _tree_estimators


_BASELINE_MODEL_NAMES = ("ridge", "zero_return", "simple_momentum", "mean_reversion")
_TREE_MODEL_NAMES = ("random_forest", "gradient_boosting")


def forecast_model_suite_at_index(
    prices: object,
    *,
    horizon: int,
    as_of_index: int | None = None,
    min_train_samples: int = 30,
    alpha: float = 10.0,
    benchmark_prices: object | None = None,
    include_tree_models: bool = True,
) -> dict:
    """Fit each fixed candidate using only labels matured by the given close."""
    values = validate_prices(prices)
    benchmark = _validate_benchmark(benchmark_prices, values.size)
    if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if not isinstance(min_train_samples, (int, np.integer)) or isinstance(min_train_samples, bool) or min_train_samples < 2:
        raise ValueError("min_train_samples must be an integer of at least 2")
    if not isinstance(include_tree_models, bool):
        raise ValueError("include_tree_models must be a boolean")
    if as_of_index is None:
        as_of_index = int(values.size - 1)
    if not isinstance(as_of_index, (int, np.integer)) or isinstance(as_of_index, bool):
        raise ValueError("as_of_index must be an integer")
    if as_of_index < 0 or as_of_index >= values.size:
        raise ValueError("as_of_index is outside the price series")

    prefix = values[:int(as_of_index) + 1]
    benchmark_prefix = benchmark[:int(as_of_index) + 1] if benchmark is not None else None
    dataset = build_supervised_dataset(prefix, int(horizon), benchmark_prefix)
    matured = dataset["target_indices"] <= int(as_of_index)
    x_train, y_train = dataset["features"][matured], dataset["targets"][matured]
    if y_train.size < min_train_samples:
        raise ValueError("insufficient matured historical labels for forecasting")
    if not np.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be finite and positive")

    feature_row = technical_features(prefix, int(as_of_index), benchmark_prefix)
    ridge = _fit_ridge(x_train, y_train, float(alpha))
    predictions = {
        "ridge": _predict(ridge, feature_row),
        "zero_return": 0.0,
    }
    trailing_return = float(prefix[-1] / prefix[-int(horizon) - 1] - 1.0)
    predictions["simple_momentum"] = trailing_return
    predictions["mean_reversion"] = -trailing_return

    tree_factories = _tree_estimators(int(min_train_samples)) if include_tree_models else {}
    models = {
        name: {
            "available": True,
            "forecast_return": float(predictions[name]),
            "training_sample_count": int(y_train.size),
        }
        for name in _BASELINE_MODEL_NAMES
    }
    for name in _TREE_MODEL_NAMES:
        factory = tree_factories.get(name)
        if factory is None:
            models[name] = {
                "available": False,
                "forecast_return": None,
                "training_sample_count": int(y_train.size),
                "reason": "not_requested" if not include_tree_models else "optional_dependency_unavailable",
                "dependency": "scikit-learn",
            }
            continue
        estimator = factory()
        estimator.fit(x_train, y_train)
        prediction = float(estimator.predict(feature_row.reshape(1, -1))[0])
        if not math.isfinite(prediction):
            raise ValueError("tree model produced a non-finite forecast")
        models[name] = {
            "available": True,
            "forecast_return": prediction,
            "training_sample_count": int(y_train.size),
        }

    return {
        "as_of_index": int(as_of_index),
        "horizon_days": int(horizon),
        "training_sample_count": int(y_train.size),
        "max_training_target_index": int(dataset["target_indices"][matured].max()),
        "purge_rule": "training_label_target_index_at_or_before_as_of_index",
        "models": models,
    }


def merge_shadow_records(existing: list[dict], proposed: list[dict]) -> tuple[list[dict], int]:
    """Append unseen forecast IDs while preserving every original prediction."""
    records = [dict(item) for item in existing]
    seen = set()
    for item in records:
        record_id = item.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("every shadow record must have a non-empty record_id")
        if record_id in seen:
            raise ValueError("shadow ledger contains a duplicate record_id")
        seen.add(record_id)

    additions = {}
    for item in proposed:
        record_id = item.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("every shadow record must have a non-empty record_id")
        if record_id in additions and additions[record_id] != item:
            raise ValueError("proposed shadow records conflict on record_id")
        additions[record_id] = dict(item)

    added = 0
    for record_id, item in additions.items():
        if record_id not in seen:
            records.append(item)
            seen.add(record_id)
            added += 1
    return records, added


def score_shadow_records(
    records: list[dict],
    closing_prices: dict[str, dict[str, float]],
    *,
    scored_at: str,
) -> tuple[list[dict], int]:
    """Fill pending realized returns only when the exact target-date close exists."""
    updated = [dict(record) for record in records]
    scored = 0
    for record in updated:
        if record.get("status") != "pending":
            continue
        symbol, origin_date, target_date = (
            record.get("symbol"), record.get("origin_date"), record.get("target_date")
        )
        series = closing_prices.get(symbol, {})
        if target_date not in series:
            continue
        origin_close = record.get("origin_close")
        target_close = series[target_date]
        if (not isinstance(origin_close, (int, float)) or not math.isfinite(origin_close)
                or origin_close <= 0 or not isinstance(target_close, (int, float))
                or not math.isfinite(target_close) or target_close <= 0):
            raise ValueError("shadow record and realized close prices must be finite and positive")
        if not isinstance(origin_date, str) or not isinstance(target_date, str) or target_date <= origin_date:
            raise ValueError("shadow record has invalid origin and target dates")
        record["actual_return"] = float(target_close / origin_close - 1.0)
        record["realized_at"] = scored_at
        record["status"] = "realized"
        scored += 1
    return updated, scored


def summarize_shadow_records(records: list[dict]) -> dict:
    """Compare realized candidates with zero on identical, non-overlapping origins."""
    grouped = {}
    for record in records:
        if record.get("status") != "realized":
            continue
        key = (record.get("symbol"), record.get("horizon_days"))
        if not isinstance(key[0], str) or not isinstance(key[1], int):
            raise ValueError("realized shadow records need a symbol and integer horizon")
        model = record.get("model")
        origin = record.get("origin_date")
        actual = record.get("actual_return")
        prediction = record.get("forecast_return")
        if (not isinstance(model, str) or not model or not isinstance(origin, str)
                or not isinstance(actual, (int, float)) or not math.isfinite(actual)
                or not isinstance(prediction, (int, float)) or not math.isfinite(prediction)):
            raise ValueError("realized shadow records contain invalid forecast values")
        grouped.setdefault(key, {}).setdefault(model, {})[origin] = record

    summaries = []
    for (symbol, horizon), model_rows in sorted(grouped.items()):
        baseline_rows = model_rows.get("zero_return", {})
        for model_name, forecast_rows in sorted(model_rows.items()):
            common_origins = sorted(set(forecast_rows).intersection(baseline_rows))
            parsed_origins = [date.fromisoformat(value) for value in common_origins]
            if any((date_b - date_a).days < horizon
                   for date_a, date_b in zip(parsed_origins, parsed_origins[1:])):
                raise ValueError("realized validation origins overlap for {} {}d".format(symbol, horizon))
            actuals = np.asarray([forecast_rows[value]["actual_return"] for value in common_origins], dtype=float)
            predictions = np.asarray([forecast_rows[value]["forecast_return"] for value in common_origins], dtype=float)
            baseline_actuals = np.asarray([baseline_rows[value]["actual_return"] for value in common_origins], dtype=float)
            if not np.allclose(actuals, baseline_actuals, rtol=0.0, atol=1e-12):
                raise ValueError("candidate and zero baseline realized returns do not align")
            errors = predictions - actuals
            mae = float(np.mean(np.abs(errors))) if actuals.size else None
            baseline_mae = float(np.mean(np.abs(baseline_actuals))) if actuals.size else None
            directional = (predictions != 0.0) & (actuals != 0.0)
            summaries.append({
                "symbol": symbol,
                "horizon_days": horizon,
                "model": model_name,
                "validation_count": int(actuals.size),
                "mae": mae,
                "rmse": float(np.sqrt(np.mean(errors ** 2))) if actuals.size else None,
                "mean_error": float(np.mean(errors)) if actuals.size else None,
                "mae_skill_vs_zero": (
                    float(1.0 - mae / baseline_mae)
                    if actuals.size and baseline_mae > 0 else None
                ),
                "directional_accuracy": (
                    float(np.mean(np.sign(predictions[directional]) == np.sign(actuals[directional])))
                    if directional.any() else None
                ),
                "directional_count": int(directional.sum()),
                "directional_coverage": float(np.mean(predictions != 0.0)) if actuals.size else None,
                "fold_step_days": horizon,
                "fees_and_slippage_included": False,
            })
    return {
        "status": "research_only",
        "validation_protocol": "frozen_forward_non_overlapping_shadow_forecasts",
        "fees_and_slippage_included": False,
        "results": summaries,
    }


def read_shadow_ledger(path: str | Path) -> list[dict]:
    """Read a JSONL shadow ledger and reject malformed or duplicate rows."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    records = []
    try:
        with ledger_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("record must be a JSON object")
                records.append(item)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("could not read shadow ledger: {}".format(exc)) from exc
    for item in records:
        if not isinstance(item.get("record_id"), str) or not item["record_id"]:
            raise ValueError("every shadow record must have a non-empty record_id")
    ids = [item["record_id"] for item in records]
    if len(ids) != len(set(ids)):
        raise ValueError("shadow ledger contains a duplicate record_id")
    return records


def write_shadow_ledger(path: str | Path, records: list[dict]) -> None:
    """Atomically replace a local JSONL ledger without permitting NaN values."""
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    for record in records:
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id or record_id in seen:
            raise ValueError("shadow records must have unique, non-empty record_id values")
        seen.add(record_id)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(ledger_path.parent),
            prefix=ledger_path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(ledger_path))
    except (OSError, TypeError, ValueError) as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        raise ValueError("could not write shadow ledger: {}".format(exc)) from exc
