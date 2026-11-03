import unittest

from tools.run_breakout_final_validation_v2 import (
    _simulate, _date_cluster_bootstrap, _metrics, _trend_regime, _split, FREEZE_DATE,
)


class FinalValidationV2Tests(unittest.TestCase):
    def candles(self):
        rows = []
        for i in range(12):
            rows.append({
                "timestamp": f"2026-01-{i+1:02d}T00:00:00+00:00",
                "open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0,
            })
        return rows

    def test_equal_distance_stop_has_same_risk_distance_for_same_entry(self):
        rows = self.candles()
        trade = _simulate(rows, 1, 1, 1.5, cost=0.30)
        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade["risk_pct"], 1.5)

    def test_stop_first_when_stop_and_target_hit_same_candle(self):
        rows = self.candles()
        rows[1]["high"] = 105.0
        rows[1]["low"] = 95.0
        trade = _simulate(rows, 1, 1, 1.5, cost=0.30)
        self.assertEqual(trade["exit_reason"], "stop_loss")

    def test_metrics_reports_drawdown_and_losing_streak(self):
        rows = [
            {"entry_timestamp": f"2026-01-0{i+1}T00:00:00+00:00",
             "net_return_pct": r, "net_r": r, "risk_pct": 1.0}
            for i, r in enumerate([-1.0, -1.0, 2.0, -1.0])
        ]
        metrics = _metrics(rows)
        self.assertEqual(metrics["max_losing_streak"], 2)
        self.assertGreater(metrics["max_drawdown_r_trade_sequence"], 0)

    def test_date_cluster_bootstrap_keeps_same_day_assets_together(self):
        pairs = []
        for day in range(30):
            for delta in (0.1, -0.05):
                pairs.append({
                    "timestamp": f"2026-02-{day+1:02d}T00:00:00+00:00",
                    "delta_r": delta,
                })
        result = _date_cluster_bootstrap(pairs, iterations=300, block=5, seed=5)
        self.assertEqual(result["date_clusters"], 30)
        self.assertEqual(result["status"], "descriptive_cross_asset_date_cluster_bootstrap")

    def test_holdout_is_strictly_after_frozen_protocol_date(self):
        self.assertEqual(FREEZE_DATE, "2026-11-03")
        split, boundary = _split(100, 150, 100)
        self.assertEqual(split, "prospective_forward_holdout")
        self.assertEqual(boundary, 150)
        historical_split, historical_boundary = _split(20, 150, 100)
        self.assertEqual(historical_split, "exploration")
        self.assertEqual(historical_boundary, 70)

    def test_trend_regime_is_independent_of_trade_side(self):
        close = [100.0 + i for i in range(70)]
        self.assertEqual(_trend_regime(close, 69), "bullish")


if __name__ == "__main__":
    unittest.main()
