"""Record frozen model forecasts to a local, research-only JSONL ledger."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio_engine.data.coingecko_history import COINGECKO_IDS, CoinGeckoHistoryClient
from portfolio_engine.forecast.prospective import (
    forecast_model_suite_at_index,
    merge_shadow_records,
    read_shadow_ledger,
    score_shadow_records,
    summarize_shadow_records,
    write_shadow_ledger,
)


SELECTION_CUTOFF = "2026-11-22"
TRACKED_CANDIDATES = {
    "BATUSD": {14: ("simple_momentum",)},
    "BEAMUSD": {30: ("simple_momentum",)},
    "HYPEUSD": {30: ("random_forest", "ridge", "gradient_boosting")},
}
TRACKED_SYMBOLS = ("BTCUSD", "BATUSD", "BEAMUSD", "HYPEUSD")
TREE_RANDOM_STATE = 1729


def _model_settings(model_name: str, horizon: int, min_train_samples: int) -> dict:
    """Describe the fixed model configuration written beside each forecast."""
    min_leaf = max(2, min(5, min_train_samples // 10))
    if model_name == "ridge":
        return {"alpha": 10.0}
    if model_name == "simple_momentum":
        return {"lookback_days": horizon}
    if model_name == "random_forest":
        return {
            "estimators": 50,
            "max_depth": 3,
            "minimum_leaf_samples": min_leaf,
            "max_features": 1.0,
            "random_state": TREE_RANDOM_STATE,
        }
    if model_name == "gradient_boosting":
        return {
            "estimators": 50,
            "learning_rate": 0.03,
            "max_depth": 1,
            "loss": "huber",
            "minimum_leaf_samples": min_leaf,
            "random_state": TREE_RANDOM_STATE,
        }
    return {}


def fetch_shadow_history(*, days: int = 365, client=None, sleep_seconds: float = 0.15) -> dict:
    """Fetch a complete price set for the frozen candidate watchlist."""
    if not 90 <= days <= 365:
        raise ValueError("days must be between 90 and 365")
    client = client or CoinGeckoHistoryClient()
    observed_at = datetime.now(timezone.utc).isoformat()
    series = {}
    for index, symbol in enumerate(TRACKED_SYMBOLS):
        rows = client.get_daily_prices(COINGECKO_IDS[symbol], days=days)
        dates = [row["date"] for row in rows]
        series[symbol] = {
            "dates": dates,
            "closes": [row["close"] for row in rows],
        }
        if index < len(TRACKED_SYMBOLS) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return {"source": "coingecko", "observed_at": observed_at, "series": series}


def _closed_aligned_prices(asset_series: dict, benchmark_series: dict,
                           before_date: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    asset = dict(zip(asset_series["dates"], asset_series["closes"]))
    benchmark = dict(zip(benchmark_series["dates"], benchmark_series["closes"]))
    dates = sorted(value for value in set(asset).intersection(benchmark) if value < before_date)
    if len(dates) < 120:
        raise ValueError("fewer than 120 closed common daily observations with BTC")
    parsed = [date.fromisoformat(value) for value in dates]
    if any((current - previous).days != 1 for previous, current in zip(parsed, parsed[1:])):
        raise ValueError("closed common price history contains missing calendar days")
    if parsed[-1] < date.fromisoformat(before_date) - timedelta(days=2):
        raise ValueError("latest closed common price is stale")
    return dates, np.asarray([asset[value] for value in dates]), np.asarray(
        [benchmark[value] for value in dates]
    )


def is_non_overlapping_origin_due(origin_date: str, last_origin_date: str | None,
                                 horizon_days: int) -> bool:
    """Allow a new origin only after the prior horizon window has ended."""
    if not isinstance(horizon_days, int) or isinstance(horizon_days, bool) or horizon_days < 1:
        raise ValueError("horizon_days must be a positive integer")
    if last_origin_date is None:
        return True
    days_apart = (date.fromisoformat(origin_date) - date.fromisoformat(last_origin_date)).days
    return days_apart >= horizon_days


def build_shadow_records(history: dict, *, min_train_samples: int = 30,
                         today_utc: date | None = None,
                         existing_records: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Build today's frozen candidate forecasts and price lookup for scoring."""
    series = history.get("series", {})
    missing = [symbol for symbol in TRACKED_SYMBOLS if symbol not in series]
    if missing:
        raise ValueError("price history is missing required symbols: {}".format(", ".join(missing)))
    today_utc = today_utc or datetime.now(timezone.utc).date()
    generated_at = datetime.now(timezone.utc).isoformat()
    observed_at = history.get("observed_at") or generated_at
    records, closing_prices = [], {}
    existing_records = existing_records or []
    benchmark = series["BTCUSD"]

    for symbol, horizon_models in TRACKED_CANDIDATES.items():
        dates, prices, benchmark_prices = _closed_aligned_prices(
            series[symbol], benchmark, today_utc.isoformat()
        )
        closing_prices[symbol] = dict(zip(dates, (float(value) for value in prices)))
        origin_date = dates[-1]
        if origin_date <= SELECTION_CUTOFF:
            raise ValueError(
                "latest closed origin {} is not after the frozen selection cutoff {}; wait for a later close".format(
                    origin_date, SELECTION_CUTOFF
                )
            )
        origin_index = len(prices) - 1

        for horizon, candidate_names in horizon_models.items():
            prior_origins = [
                item["origin_date"] for item in existing_records
                if item.get("symbol") == symbol
                and item.get("horizon_days") == horizon
                and isinstance(item.get("origin_date"), str)
            ]
            last_origin = max(prior_origins) if prior_origins else None
            if not is_non_overlapping_origin_due(origin_date, last_origin, horizon):
                continue
            forecast = forecast_model_suite_at_index(
                prices,
                horizon=horizon,
                as_of_index=origin_index,
                min_train_samples=min_train_samples,
                benchmark_prices=benchmark_prices,
                include_tree_models=True,
            )
            names = tuple(candidate_names) + ("zero_return",)
            for model_name in names:
                model = forecast["models"][model_name]
                if not model["available"]:
                    reason = model.get("reason", "unavailable")
                    raise RuntimeError(
                        "required frozen model {} is unavailable: {}".format(model_name, reason)
                    )
                records.append({
                    "record_id": "{}|{}|{}|{}".format(symbol, horizon, model_name, origin_date),
                    "symbol": symbol,
                    "horizon_days": int(horizon),
                    "model": model_name,
                    "model_settings": _model_settings(model_name, horizon, min_train_samples),
                    "model_bundle_version": "black_litterman_forecast_suite_v1",
                    "origin_date": origin_date,
                    "target_date": (date.fromisoformat(origin_date) + timedelta(days=horizon)).isoformat(),
                    "origin_close": float(prices[-1]),
                    "forecast_return": float(model["forecast_return"]),
                    "actual_return": None,
                    "status": "pending",
                    "generated_at": generated_at,
                    "source_observed_at": observed_at,
                    "source": "coingecko",
                    "training_sample_count": forecast["training_sample_count"],
                    "model_selection_cutoff": SELECTION_CUTOFF,
                    "selection_protocol": "frozen_from_retrospective_comparison; no retuning",
                    "validation_protocol": "expanding_purged_mature_labels_at_closed_price_origin",
                    "target_definition": "close[t+horizon_days] / close[t] - 1",
                    "fees_and_slippage_included": False,
                    "no_live_orders": True,
                    "portfolio_eligibility_changed": False,
                    "realized_at": None,
                })

    records.sort(key=lambda item: (
        item["symbol"], item["horizon_days"], item["model"]
    ))
    return records, closing_prices


def update_shadow_ledger(path: str | Path, proposed: list[dict],
                         closing_prices: dict[str, dict[str, float]],
                         *, scored_at: str,
                         existing_records: list[dict] | None = None) -> dict:
    """Score mature records, add unseen origins, then atomically save locally."""
    existing = read_shadow_ledger(path) if existing_records is None else existing_records
    scored_records, scored_count = score_shadow_records(
        existing, closing_prices, scored_at=scored_at
    )
    merged, added_count = merge_shadow_records(scored_records, proposed)
    performance = summarize_shadow_records(merged)
    if scored_count or added_count:
        write_shadow_ledger(path, merged)
    return {
        "new_forecasts": added_count,
        "newly_realized": scored_count,
        "pending_forecasts": sum(record.get("status") == "pending" for record in merged),
        "realized_forecasts": sum(record.get("status") == "realized" for record in merged),
        "ledger_path": str(path),
        "mode": "local_shadow_validation",
        "no_live_orders": True,
        "portfolio_eligibility_changed": False,
        "status": "research_only",
        "prospective_metrics": performance,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365, help="CoinGecko price history window (90–365 days)")
    parser.add_argument("--min-train-samples", type=int, default=30)
    parser.add_argument("--ledger", type=Path, required=True,
                        help="Local JSONL file for shadow forecasts; never uploaded by this script")
    args = parser.parse_args()

    try:
        existing = read_shadow_ledger(args.ledger)
        history = fetch_shadow_history(days=args.days)
        proposed, closing_prices = build_shadow_records(
            history, min_train_samples=args.min_train_samples,
            existing_records=existing,
        )
        summary = update_shadow_ledger(
            args.ledger,
            proposed,
            closing_prices,
            scored_at=datetime.now(timezone.utc).isoformat(),
            existing_records=existing,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, "Shadow validation stopped without updating the local ledger: {}\n".format(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
