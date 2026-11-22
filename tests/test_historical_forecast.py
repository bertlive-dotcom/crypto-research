"""Tests for causal feature generation and expanding walk-forward forecasts."""
import unittest

try:
    import numpy as np
except ImportError as exc:
    raise unittest.SkipTest("NumPy is required for the historical forecast suite") from exc

from portfolio_engine.forecast import build_supervised_dataset, forecast_at_index, forecast_latest, walk_forward_validate
from portfolio_engine.forecast.features import technical_features


def synthetic_prices(size=240):
    rng = np.random.default_rng(2026)
    returns = rng.normal(0.0008, 0.018, size=size - 1)
    return 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + returns]))


class FeatureTests(unittest.TestCase):
    def test_feature_row_is_finite_and_has_expected_shape(self):
        row = technical_features(synthetic_prices(), 100)
        self.assertEqual(row.shape, (8,))
        self.assertTrue(np.isfinite(row).all())

    def test_feature_row_does_not_read_future_prices(self):
        prices = synthetic_prices()
        changed = prices.copy()
        changed[101:] *= 5.0
        np.testing.assert_allclose(technical_features(prices, 100), technical_features(changed, 100))

    def test_relative_strength_features_compare_asset_with_btc(self):
        benchmark = np.linspace(100.0, 120.0, 100)
        asset = np.linspace(100.0, 150.0, 100)
        row = technical_features(asset, 99, benchmark)
        self.assertGreater(row[6], 0.0)
        self.assertGreater(row[7], 0.0)

    def test_relative_strength_is_causal_for_both_series(self):
        prices, benchmark = synthetic_prices(), synthetic_prices() * 1.2
        changed_prices, changed_benchmark = prices.copy(), benchmark.copy()
        changed_prices[101:] *= 2.0
        changed_benchmark[101:] *= 0.5
        np.testing.assert_allclose(
            technical_features(prices, 100, benchmark),
            technical_features(changed_prices, 100, changed_benchmark),
        )

    def test_rejects_misaligned_benchmark(self):
        with self.assertRaises(ValueError):
            technical_features(synthetic_prices(), 100, synthetic_prices(200))

    def test_rejects_invalid_prices(self):
        with self.assertRaises(ValueError):
            technical_features([1.0, 2.0], 1)


class DatasetTests(unittest.TestCase):
    def test_forward_labels_and_indices_are_exact(self):
        prices = np.arange(1.0, 101.0)
        dataset = build_supervised_dataset(prices, horizon=7)
        first = dataset["origin_indices"][0]
        self.assertEqual(first, 39)
        self.assertAlmostEqual(dataset["targets"][0], prices[first + 7] / prices[first] - 1.0)
        self.assertEqual(dataset["target_indices"][0], first + 7)

    def test_rejects_invalid_horizon(self):
        with self.assertRaises(ValueError):
            build_supervised_dataset(synthetic_prices(), horizon=0)

    def test_dataset_contains_btc_relative_features(self):
        asset = synthetic_prices()
        benchmark = synthetic_prices() * 1.1
        dataset = build_supervised_dataset(asset, horizon=7, benchmark_prices=benchmark)
        self.assertEqual(dataset["features"].shape[1], 8)
        self.assertIn("relative_momentum_30d_vs_btc", dataset["feature_names"])


class WalkForwardTests(unittest.TestCase):
    def test_predictions_use_only_matured_training_labels(self):
        prices = synthetic_prices(220)
        dataset = build_supervised_dataset(prices, horizon=7)
        result = forecast_at_index(prices, 150, horizon=7, min_train_samples=30)
        self.assertEqual(result["training_sample_count"], int(np.sum(dataset["target_indices"] <= 150)))

    def test_historical_prediction_is_unchanged_by_later_data(self):
        prices = synthetic_prices(220)
        changed = prices.copy()
        changed[158:] *= 1.7
        a = forecast_at_index(prices, 150, horizon=7, min_train_samples=30)
        b = forecast_at_index(changed, 150, horizon=7, min_train_samples=30)
        self.assertAlmostEqual(a["forecast_return"], b["forecast_return"], places=12)

    def test_walk_forward_outputs_out_of_sample_metrics_and_zero_baseline(self):
        result = walk_forward_validate(synthetic_prices(240), horizon=7, min_train_samples=30)
        self.assertGreater(result["validation_count"], 20)
        self.assertGreaterEqual(result["mae"], 0.0)
        self.assertGreaterEqual(result["zero_baseline_mae"], 0.0)
        self.assertIsNotNone(result["mae_skill_vs_zero"])
        self.assertGreaterEqual(result["directional_accuracy"], 0.0)
        self.assertLessEqual(result["directional_accuracy"], 1.0)

    def test_latest_forecast_never_qualifies_without_positive_out_of_sample_skill(self):
        result = forecast_latest(synthetic_prices(240), horizon=7, min_train_samples=30,
                                 min_validation_samples=20)
        self.assertGreaterEqual(result["walk_forward_validation_count"], 20)
        self.assertEqual(result["view_eligible"], result["mae_skill_vs_zero"] > 0.0)
        self.assertIn(result["evidence_level"], {"low", "moderate", "high"})
        self.assertLess(result["lower_bound_90"], result["forecast_return"])
        self.assertGreater(result["upper_bound_90"], result["forecast_return"])

    def test_walk_forward_uses_btc_relative_features(self):
        prices, benchmark = synthetic_prices(240), synthetic_prices(240) * 1.3
        result = walk_forward_validate(prices, horizon=7, min_train_samples=30,
                                       benchmark_prices=benchmark)
        self.assertGreater(result["validation_count"], 20)


if __name__ == "__main__":
    unittest.main()
