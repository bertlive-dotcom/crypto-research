"""Tests for frozen, local prospective forecast tracking."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from portfolio_engine.forecast.prospective import (
    forecast_model_suite_at_index,
    merge_shadow_records,
    read_shadow_ledger,
    score_shadow_records,
    summarize_shadow_records,
    write_shadow_ledger,
)
from scripts.track_black_litterman_forecasts import (
    build_shadow_records,
    is_non_overlapping_origin_due,
)


def synthetic_prices(size=380):
    rng = np.random.default_rng(20261122)
    changes = 0.0004 + 0.006 * np.sin(np.arange(size - 1) / 13.0)
    changes += rng.normal(0.0, 0.018, size=size - 1)
    return 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + changes]))


def shadow_record(**overrides):
    record = {
        "record_id": "BATUSD|14|simple_momentum|2026-11-22",
        "symbol": "BATUSD",
        "horizon_days": 14,
        "model": "simple_momentum",
        "origin_date": "2026-11-22",
        "target_date": "2026-12-06",
        "origin_close": 100.0,
        "forecast_return": 0.04,
        "status": "pending",
        "actual_return": None,
        "realized_at": None,
    }
    record.update(overrides)
    return record


class ProspectiveForecastTests(unittest.TestCase):
    def test_new_origins_wait_until_the_prior_horizon_window_finishes(self):
        self.assertFalse(is_non_overlapping_origin_due("2026-12-07", "2026-11-24", 14))
        self.assertTrue(is_non_overlapping_origin_due("2026-12-08", "2026-11-24", 14))
        self.assertFalse(is_non_overlapping_origin_due("2026-12-23", "2026-11-24", 30))
        self.assertTrue(is_non_overlapping_origin_due("2026-12-24", "2026-11-24", 30))

    def test_forecast_models_use_only_prices_through_the_as_of_index(self):
        prices = synthetic_prices()
        as_of = 300
        benchmark = synthetic_prices() * 0.8
        first = forecast_model_suite_at_index(
            prices, horizon=14, as_of_index=as_of, min_train_samples=30,
            benchmark_prices=benchmark,
        )
        revised_future = prices.copy()
        revised_future[as_of + 1:] *= 7.0
        second = forecast_model_suite_at_index(
            revised_future, horizon=14, as_of_index=as_of, min_train_samples=30,
            benchmark_prices=benchmark,
        )
        self.assertEqual(first["training_sample_count"], second["training_sample_count"])
        self.assertLessEqual(first["max_training_target_index"], as_of)
        for name in ("ridge", "zero_return", "simple_momentum", "mean_reversion"):
            with self.subTest(model=name):
                self.assertEqual(first["models"][name]["forecast_return"],
                                 second["models"][name]["forecast_return"])
        self.assertEqual(first["models"]["zero_return"]["forecast_return"], 0.0)
        self.assertAlmostEqual(
            first["models"]["simple_momentum"]["forecast_return"],
            prices[as_of] / prices[as_of - 14] - 1.0,
        )

    def test_tree_models_are_explicitly_unavailable_when_not_requested(self):
        result = forecast_model_suite_at_index(
            synthetic_prices(), horizon=30, min_train_samples=30,
            include_tree_models=False,
        )
        for name in ("random_forest", "gradient_boosting"):
            with self.subTest(model=name):
                self.assertFalse(result["models"][name]["available"])
                self.assertEqual(result["models"][name]["reason"], "not_requested")

    def test_shadow_records_freeze_candidates_at_last_closed_utc_date(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest("scikit-learn is required for the frozen tree candidates")
        dates = [
            (date(2025, 11, 25) + timedelta(days=index)).isoformat()
            for index in range(366)
        ]
        series = {"BTCUSD": {"dates": dates, "closes": synthetic_prices(366).tolist()}}
        for offset, symbol in enumerate(("BATUSD", "BEAMUSD", "HYPEUSD"), start=1):
            series[symbol] = {
                "dates": dates,
                "closes": (synthetic_prices(366) * (1.0 + 0.1 * offset)).tolist(),
            }
        proposed, closes = build_shadow_records(
            {"observed_at": "2026-11-23T08:00:00Z", "series": series},
            today_utc=date(2026, 11, 25),
        )
        self.assertEqual(len(proposed), 8)
        self.assertEqual({record["origin_date"] for record in proposed}, {"2026-11-24"})
        self.assertEqual({record["target_date"] for record in proposed},
                         {"2026-12-08", "2026-12-24"})
        self.assertEqual(len({record["record_id"] for record in proposed}), 8)
        self.assertFalse(any(record["portfolio_eligibility_changed"] for record in proposed))
        self.assertEqual(len(closes["HYPEUSD"]), 365)

    def test_shadow_tracker_rejects_origins_before_the_selection_cutoff(self):
        dates = [
            (date(2025, 11, 23) + timedelta(days=index)).isoformat()
            for index in range(366)
        ]
        series = {"BTCUSD": {"dates": dates, "closes": synthetic_prices(366).tolist()}}
        for symbol in ("BATUSD", "BEAMUSD", "HYPEUSD"):
            series[symbol] = {"dates": dates, "closes": synthetic_prices(366).tolist()}
        with self.assertRaisesRegex(ValueError, "not after the frozen selection cutoff"):
            build_shadow_records(
                {"observed_at": "2026-11-23T08:00:00Z", "series": series},
                today_utc=date(2026, 11, 23),
            )


class ShadowLedgerTests(unittest.TestCase):
    def test_merge_is_idempotent_and_does_not_rewrite_an_existing_forecast(self):
        original = shadow_record()
        revised = shadow_record(forecast_return=-0.5)
        merged, added = merge_shadow_records([original], [revised])
        self.assertEqual(added, 0)
        self.assertEqual(merged, [original])
        merged, added = merge_shadow_records(merged, [shadow_record(
            record_id="BATUSD|14|zero_return|2026-11-22", model="zero_return",
            forecast_return=0.0,
        )])
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)

    def test_scoring_waits_for_exact_target_date_and_is_idempotent(self):
        pending = shadow_record()
        early, scored = score_shadow_records(
            [pending], {"BATUSD": {"2026-12-05": 110.0}}, scored_at="2026-12-05T12:00:00Z"
        )
        self.assertEqual(scored, 0)
        self.assertEqual(early[0]["status"], "pending")

        completed, scored = score_shadow_records(
            early, {"BATUSD": {"2026-12-06": 112.0}}, scored_at="2026-12-06T12:00:00Z"
        )
        self.assertEqual(scored, 1)
        self.assertEqual(completed[0]["status"], "realized")
        self.assertAlmostEqual(completed[0]["actual_return"], 0.12)
        self.assertEqual(completed[0]["realized_at"], "2026-12-06T12:00:00Z")
        unchanged, scored = score_shadow_records(
            completed, {"BATUSD": {"2026-12-06": 90.0}}, scored_at="2026-12-07T12:00:00Z"
        )
        self.assertEqual(scored, 0)
        self.assertEqual(unchanged[0]["actual_return"], completed[0]["actual_return"])

    def test_jsonl_round_trip_and_malformed_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            expected = [shadow_record()]
            write_shadow_ledger(path, expected)
            self.assertEqual(read_shadow_ledger(path), expected)
            path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_shadow_ledger(path)

    def test_metrics_compare_candidates_with_zero_on_matching_non_overlapping_origins(self):
        realized = []
        for origin, target, actual, prediction in (
            ("2026-11-24", "2026-12-08", 0.10, 0.08),
            ("2026-12-08", "2026-12-22", -0.05, -0.04),
        ):
            for model, forecast in (("simple_momentum", prediction), ("zero_return", 0.0)):
                realized.append({
                    "symbol": "BATUSD",
                    "horizon_days": 14,
                    "model": model,
                    "origin_date": origin,
                    "target_date": target,
                    "forecast_return": forecast,
                    "actual_return": actual,
                    "status": "realized",
                })
        summary = summarize_shadow_records(realized)
        candidate = next(item for item in summary["results"] if item["model"] == "simple_momentum")
        self.assertEqual(candidate["validation_count"], 2)
        self.assertAlmostEqual(candidate["mae"], 0.015)
        self.assertAlmostEqual(candidate["mae_skill_vs_zero"], 0.8)
        self.assertEqual(candidate["directional_accuracy"], 1.0)
        self.assertFalse(candidate["fees_and_slippage_included"])

    def test_metrics_reject_overlapping_realized_origins(self):
        records = []
        for origin, actual in (("2026-11-24", 0.1), ("2026-12-01", -0.05)):
            for model, forecast in (("simple_momentum", 0.02), ("zero_return", 0.0)):
                records.append({
                    "symbol": "BATUSD", "horizon_days": 14, "model": model,
                    "origin_date": origin, "target_date": origin,
                    "forecast_return": forecast, "actual_return": actual,
                    "status": "realized",
                })
        with self.assertRaisesRegex(ValueError, "origins overlap"):
            summarize_shadow_records(records)


if __name__ == "__main__":
    unittest.main()
