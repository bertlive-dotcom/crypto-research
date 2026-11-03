import unittest

from tools.run_paired_breakout_retest_final_holdout import (
    moving_block_bootstrap, _stats,
)


class PairedBreakoutRetestTests(unittest.TestCase):
    def test_block_bootstrap_is_deterministic_and_preserves_small_sample_guard(self):
        self.assertEqual(
            moving_block_bootstrap([0.1] * 19)["status"],
            "insufficient_for_bootstrap",
        )
        values = [0.2, -0.1, 0.3, 0.1, -0.2] * 8
        a = moving_block_bootstrap(values, iterations=300, block=5, seed=7)
        b = moving_block_bootstrap(values, iterations=300, block=5, seed=7)
        self.assertEqual(a, b)
        self.assertEqual(a["n"], len(values))
        self.assertEqual(a["block_length_events"], 5)

    def test_cost_sensitivity_is_applied_once_to_gross_return(self):
        trade = {"gross_return_pct": 1.0, "risk_pct": 0.5}
        at_030 = _stats([trade], cost=0.30)
        at_075 = _stats([trade], cost=0.75)
        self.assertAlmostEqual(at_030["mean_net_pct"], 0.7)
        self.assertAlmostEqual(at_075["mean_net_pct"], 0.25)
        self.assertAlmostEqual(at_030["mean_net_r"], 1.4)
        self.assertAlmostEqual(at_075["mean_net_r"], 0.5)


if __name__ == "__main__":
    unittest.main()
