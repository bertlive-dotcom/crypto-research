import unittest

from tools.run_paired_breakout_retest_final_holdout import (
    moving_block_bootstrap, date_cluster_moving_block_bootstrap, _stats, _date_key,
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

    def test_date_cluster_bootstrap_groups_assets_on_same_day(self):
        events = []
        for day in range(30):
            events.append({
                "breakout_timestamp": f"2026-01-{day + 1:02d}T00:00:00+00:00",
                "paired_delta_net_r": 0.1 if day % 2 == 0 else -0.05,
            })
            # Same-day second asset belongs to the same date cluster.
            events.append({
                "breakout_timestamp": f"2026-01-{day + 1:02d}T12:00:00+00:00",
                "paired_delta_net_r": 0.2 if day % 2 == 0 else -0.1,
            })
        self.assertEqual(_date_key(events[0]["breakout_timestamp"]),
                         _date_key(events[1]["breakout_timestamp"]))
        result = date_cluster_moving_block_bootstrap(events, iterations=300, block_dates=5, seed=9)
        self.assertEqual(result["date_clusters"], 30)
        self.assertEqual(result["events"], 60)
        self.assertEqual(result["status"], "cross_asset_date_cluster_moving_block_descriptive_interval")

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
