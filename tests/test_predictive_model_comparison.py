"""Tests for purged, non-overlapping predictive model comparisons."""
import unittest

try:
    import numpy as np
except ImportError as exc:
    raise unittest.SkipTest("NumPy is required for forecast comparison tests") from exc

from portfolio_engine.forecast.comparison import build_model_comparison_report
from portfolio_engine.forecast.dataset import build_supervised_dataset
from portfolio_engine.forecast.walk_forward import walk_forward_validate
from scripts.compare_black_litterman_forecasts import build_watchlist_report


def synthetic_prices(size=380):
    rng = np.random.default_rng(20261122)
    index = np.arange(size - 1, dtype=float)
    returns = 0.0004 + 0.006 * np.sin(index / 13.0) + rng.normal(0.0, 0.018, size=size - 1)
    return 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + returns]))


class NonOverlappingWalkForwardTests(unittest.TestCase):
    def test_validation_origins_are_spaced_by_the_forecast_horizon(self):
        prices = synthetic_prices()
        for horizon in (3, 7, 14, 30):
            with self.subTest(horizon=horizon):
                result = walk_forward_validate(prices, horizon=horizon, min_train_samples=30)
                origins = np.asarray(result["origins"], dtype=int)
                self.assertGreater(origins.size, 0)
                np.testing.assert_array_equal(np.diff(origins), np.full(origins.size - 1, horizon))
                ends = np.asarray(result["evaluation_end_indices"], dtype=int)
                np.testing.assert_array_equal(ends, origins + horizon)
                self.assertEqual(result["fold_step_days"], horizon)

    def test_each_fold_purges_labels_that_have_not_matured(self):
        horizon = 14
        result = walk_forward_validate(synthetic_prices(), horizon=horizon, min_train_samples=30)
        dataset = build_supervised_dataset(synthetic_prices(), horizon=horizon)
        for fold in result["folds"]:
            origin = fold["origin_index"]
            matured = dataset["target_indices"] <= origin
            self.assertLessEqual(fold["max_training_target_index"], origin)
            self.assertEqual(fold["training_sample_count"], int(matured.sum()))
            self.assertEqual(
                fold["max_training_target_index"],
                int(dataset["target_indices"][matured].max()),
            )

    def test_baselines_share_the_ridge_validation_origins(self):
        prices = synthetic_prices()
        result = walk_forward_validate(prices, horizon=7, min_train_samples=30)
        expected_models = {"ridge", "zero_return", "simple_momentum", "mean_reversion",
                           "random_forest", "gradient_boosting"}
        self.assertTrue(expected_models.issubset(result["model_metrics"]))
        for name in expected_models:
            with self.subTest(model=name):
                predictions = result["model_predictions"][name]
                metrics = result["model_metrics"][name]
                if metrics["available"]:
                    self.assertEqual(len(predictions), result["validation_count"])
                    self.assertEqual(metrics["validation_count"], result["validation_count"])
                    for metric in ("mae", "rmse", "directional_coverage", "mean_error",
                                   "mae_skill_vs_zero"):
                        self.assertTrue(np.isfinite(metrics[metric]))
                    if metrics["directional_accuracy"] is None:
                        self.assertEqual(metrics["directional_count"], 0)
                    else:
                        self.assertTrue(np.isfinite(metrics["directional_accuracy"]))
                else:
                    self.assertEqual(predictions, [])
                    self.assertIn(metrics["reason"], {"not_requested", "optional_dependency_unavailable"})
        zero_predictions = np.asarray(result["model_predictions"]["zero_return"])
        np.testing.assert_array_equal(zero_predictions, np.zeros_like(zero_predictions))
        momentum = np.asarray([
            prices[origin] / prices[origin - 7] - 1.0 for origin in result["origins"]
        ])
        np.testing.assert_allclose(result["model_predictions"]["simple_momentum"], momentum)
        np.testing.assert_allclose(result["model_predictions"]["mean_reversion"], -momentum)
        np.testing.assert_allclose(
            result["model_metrics"]["zero_return"]["mae"],
            np.mean(np.abs(np.asarray(result["actuals"]))),
        )
        self.assertAlmostEqual(result["model_metrics"]["ridge"]["mae"], result["mae"])
        self.assertAlmostEqual(result["model_metrics"]["zero_return"]["mae_skill_vs_zero"], 0.0)
        self.assertIsNone(result["model_metrics"]["zero_return"]["directional_accuracy"])

    def test_horizon_report_includes_metrics_and_limitations(self):
        report = build_model_comparison_report(synthetic_prices(), min_train_samples=30)
        self.assertEqual(report["horizons_days"], [3, 7, 14, 30])
        self.assertEqual(report["validation_protocol"], "expanding_non_overlapping_purged_walk_forward")
        self.assertTrue(report["limitations"])
        self.assertTrue(report["read_only"])
        self.assertIn("does not qualify", report["eligibility_policy"])
        for horizon in ("3", "7", "14", "30"):
            with self.subTest(horizon=horizon):
                result = report["results"][horizon]
                self.assertGreater(result["validation_count"], 0)
                self.assertEqual(result["fold_step_days"], int(horizon))
                for name in ("ridge", "zero_return", "simple_momentum", "mean_reversion",
                             "random_forest", "gradient_boosting"):
                    self.assertIn(name, result["models"])

    def test_optional_tree_estimators_run_when_scikit_learn_is_installed(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest("scikit-learn is an optional research comparison dependency")
        result = walk_forward_validate(synthetic_prices(220), horizon=30,
                                       min_train_samples=30, include_tree_models=True)
        self.assertEqual(result["model_metrics"]["random_forest"]["available"], True)
        self.assertEqual(result["model_metrics"]["gradient_boosting"]["available"], True)
        self.assertEqual(result["model_metrics"]["random_forest"]["validation_count"],
                         result["validation_count"])
        self.assertEqual(result["model_metrics"]["gradient_boosting"]["validation_count"],
                         result["validation_count"])

    def test_watchlist_report_fails_closed_without_btc_history(self):
        report = build_watchlist_report({
            "source": "test", "unavailable": [{"symbol": "BTCUSD", "reason": "history_fetch_failed"}],
        })
        self.assertEqual(report["status"], "insufficient_history")
        self.assertEqual(report["assets"], {})
        self.assertTrue(report["unavailable"])
        self.assertFalse(report["portfolio_eligibility_changed"])


if __name__ == "__main__":
    unittest.main()
