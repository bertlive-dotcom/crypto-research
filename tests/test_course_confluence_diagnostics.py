import unittest

from research.course_confluence.diagnostics import (
    adx, confirmed_pivots, ema, fvg_zones, stochastic, wick_profile, weekly_trend,
)


class CourseDiagnosticsTests(unittest.TestCase):
    def candles(self, count=80):
        rows = []
        for i in range(count):
            close = 100 + i * 0.5
            rows.append({
                "open": close - 0.2, "high": close + 1,
                "low": close - 1, "close": close, "volume": 1000 + i,
            })
        return rows

    def test_ema_has_no_values_before_warmup(self):
        values = ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(values[:2], [None, None])
        self.assertIsNotNone(values[-1])

    def test_stochastic_1433_returns_smoothed_series(self):
        result = stochastic(self.candles(40))
        self.assertIsNotNone(result["k"][-1])
        self.assertIsNotNone(result["d"][-1])
        self.assertGreaterEqual(result["k"][-1], 0)
        self.assertLessEqual(result["k"][-1], 100)

    def test_adx_is_strength_and_directional_lines_are_separate(self):
        result = adx(self.candles(80))
        self.assertIsNotNone(result["adx"][-1])
        self.assertIsNotNone(result["plus_di"][-1])
        self.assertIsNotNone(result["minus_di"][-1])
        self.assertGreaterEqual(result["adx"][-1], 0)
        self.assertLessEqual(result["adx"][-1], 100)

    def test_pivot_is_only_confirmed_after_right_bars(self):
        rows = self.candles(15)
        rows[7]["high"] = 150
        pivots = confirmed_pivots(rows, left=2, right=2)
        found = next(x for x in pivots["highs"] if x["pivot_index"] == 7)
        self.assertEqual(found["confirmed_at_index"], 9)

    def test_fvg_three_candle_gap_is_objective(self):
        rows = self.candles(3)
        rows[0].update({"high": 101, "low": 99})
        rows[2].update({"high": 105, "low": 102})
        zones = fvg_zones(rows)
        self.assertEqual(zones[-1]["direction"], "bullish")
        self.assertEqual(zones[-1]["lower"], 101)
        self.assertEqual(zones[-1]["upper"], 102)

    def test_wick_profile_flags_rejection_candidate(self):
        result = wick_profile({"open": 100, "high": 101, "low": 90, "close": 100.5})
        self.assertTrue(result["lower_rejection_candidate"])
        self.assertFalse(result["upper_rejection_candidate"])

    def test_weekly_ema50_requires_sufficient_history(self):
        self.assertEqual(weekly_trend(self.candles(40))["status"], "insufficient_history")
        self.assertEqual(weekly_trend(self.candles(60))["status"], "available")


if __name__ == "__main__":
    unittest.main()
