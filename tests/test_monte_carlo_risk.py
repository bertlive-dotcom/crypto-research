import unittest

from research.monte_carlo.simulator import simulate, trades_to_r_multiples
from research.monte_carlo.runner import build_report


class MonteCarloRiskTests(unittest.TestCase):
    def test_trade_rows_convert_to_net_r(self):
        rows = [{"entry": 100, "stop": 98, "net_return_pct": 2.0}]
        self.assertAlmostEqual(trades_to_r_multiples(rows)[0], 1.0)

    def test_rejects_missing_stop_or_zero_risk(self):
        with self.assertRaises(ValueError):
            trades_to_r_multiples([{"entry": 100, "net_return_pct": 1}])
        with self.assertRaises(ValueError):
            trades_to_r_multiples([{"entry": 100, "stop": 100, "net_return_pct": 1}])

    def test_simulation_is_reproducible(self):
        values = [1.0, -1.0, 0.5, -0.5, 2.0, -1.0] * 5
        a = simulate(values, simulations=200, seed=7)
        b = simulate(values, simulations=200, seed=7)
        self.assertEqual(a, b)
        self.assertEqual(a["simulations"], 200)
        self.assertIn("moving_block_bootstrap", a)

    def test_rejects_invalid_parameters(self):
        with self.assertRaises(ValueError):
            simulate([1, -1], simulations=0)
        with self.assertRaises(ValueError):
            simulate([1, -1], risk_per_trade_pct=100)

    def test_build_report_accepts_actual_flat_schema_and_splits_samples(self):
        trades = []
        for i in range(24):
            trades.append({
                "entry": 100, "stop": 99,
                "net_return_pct": 1 if i % 2 == 0 else -1,
                "holdout": i >= 16,
            })
        source = {
            "report_type": "read_only_breakout_retest_research",
            "assets": [{"symbol": "BTCUSDT", "trades": trades}],
        }
        result = build_report(source, simulations=50)
        sample = result["assets"][0]["sample"]
        self.assertEqual(sample["exploration"]["sample_trades"], 16)
        self.assertEqual(sample["holdout"]["sample_trades"], 8)
        self.assertEqual(sample["holdout"]["status"], "insufficient_sample")

    def test_legacy_report_without_entry_stop_is_not_simulated(self):
        trades = [
            {"entry_date": "2025-01-01", "net_return_pct": 1.0, "holdout": False},
            {"entry_date": "2026-01-01", "net_return_pct": -1.0, "holdout": True},
        ]
        source = {"assets": [{"symbol": "BTCUSDT", "trades": trades}]}
        result = build_report(source)
        sample = result["assets"][0]["sample"]
        self.assertEqual(sample["exploration"]["status"], "incomplete_trade_data")
        self.assertEqual(sample["exploration"]["missing_fields"], ["entry", "stop"])
        self.assertEqual(sample["holdout"]["status"], "incomplete_trade_data")

    def test_legacy_nested_schema_remains_supported(self):
        trades = [{"entry": 100, "stop": 99, "net_return_pct": 1.0, "holdout": False}]
        source = {"assets": [{"symbol": "BTCUSDT", "breakout_retest": {"trades": trades}}]}
        result = build_report(source)
        self.assertEqual(
            result["assets"][0]["sample"]["exploration"]["status"],
            "insufficient_sample",
        )


if __name__ == "__main__":
    unittest.main()
