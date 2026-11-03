import unittest

from tools.run_breakout_retest_robustness import _stats, _bootstrap_mean_ci, _regimes


class BreakoutRetestRobustnessTests(unittest.TestCase):
    def test_cost_sensitivity_subtracts_cost_from_gross_returns(self):
        result = _stats([
            {"gross_return_pct": 1.0},
            {"gross_return_pct": -0.4},
        ], 0.5)
        self.assertEqual(result["trades"], 2)
        self.assertAlmostEqual(result["mean_net_return_pct"], -0.2)

    def test_small_sample_is_not_labelled_as_validated(self):
        result = _stats([{"gross_return_pct": 0.5}] * 5, 0.3)
        self.assertEqual(result["sample_status"], "descriptive_only")

    def test_bootstrap_refuses_tiny_samples(self):
        result = _bootstrap_mean_ci([0.1, -0.1])
        self.assertEqual(result["status"], "too_few_trades")
        self.assertIsNone(result["lower_95_pct"])

    def test_regime_classification_uses_exact_candle_timestamps(self):
        candles = [
            {"timestamp": "2026-01-01T00:00:00", "close": 10},
            {"timestamp": "2026-01-01T04:00:00", "close": 11},
        ]
        labels = _regimes(candles)
        self.assertEqual(set(labels), {"2026-01-01T00:00:00", "2026-01-01T04:00:00"})


if __name__ == "__main__":
    unittest.main()
