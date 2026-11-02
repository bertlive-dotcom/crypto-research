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

    def test_build_report_keeps_exploration_and_holdout_separate(self):
        trades = []
        for i in range(24):
            trades.append({
                "entry": 100, "stop": 99, "net_return_pct": 1 if i % 2 == 0 else -1,
                "holdout": i >= 16,
            })
        source = {"report_type": "read_only_breakout_retest_research",
                  "assets": [{"symbol": "BTCUSDT", "breakout_retest": {"trades": trades}}]}
        result = build_report(source, simulations=50)
        sample = result["assets"][0]["sample"]
        self.assertEqual(sample["exploration"]["sample_trades"], 16)
        self.assertEqual(sample["holdout"]["sample_trades"], 8)
        self.assertEqual(sample["holdout"]["status"], "insufficient_sample")


if __name__ == "__main__":
    unittest.main()
