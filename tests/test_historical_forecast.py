"""Tests for causal feature generation and expanding walk-forward forecasts."""
import unittest
import numpy as np
from portfolio_engine.forecast import build_supervised_dataset, forecast_at_index, forecast_latest, walk_forward_validate
from portfolio_engine.forecast.features import technical_features


def synthetic_prices(size=240):
    rng = np.random.default_rng(2026)
    returns = rng.normal(0.0008, 0.018, size=size - 1)
    return 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + returns]))


class FeatureTests(unittest.TestCase):
    def test_feature_row_is_finite_and_has_expected_shape(self):
        row = technical_features(synthetic_prices(), 100)
        self.assertEqual(row.shape, (6,))
        self.assertTrue(np.isfinite(row).all())

    def test_feature_row_does_not_read_future_prices(self):
        prices = synthetic_prices()
        changed = prices.copy()
        changed[101:] *= 5.0
        np.testing.assert_allclose(technical_features(prices, 100), technical_features(changed, 100))

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

    def test_walk_forward_outputs_out_of_sample_metrics(self):
        result = walk_forward_validate(synthetic_prices(240), horizon=7, min_train_samples=30)
        self.assertGreater(result["validation_count"], 20)
        self.assertGreaterEqual(result["mae"], 0.0)
        self.assertGreaterEqual(result["directional_accuracy"], 0.0)
        self.assertLessEqual(result["directional_accuracy"], 1.0)

    def test_latest_forecast_has_calibrated_interval_and_provenance(self):
        result = forecast_latest(synthetic_prices(240), horizon=7, min_train_samples=30,
                                 min_validation_samples=20)
        self.assertTrue(result["view_eligible"])
        self.assertLess(result["lower_bound_90"], result["forecast_return"])
        self.assertGreater(result["upper_bound_90"], result["forecast_return"])
        self.assertGreaterEqual(result["walk_forward_validation_count"], 20)
        self.assertIn(result["evidence_level"], {"low", "moderate", "high"})


if __name__ == "__main__":
    unittest.main()
