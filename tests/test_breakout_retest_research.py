from datetime import datetime, timedelta, timezone
import unittest

from tools.run_breakout_retest_research import evaluate


def _candles(count=260):
    rows = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    for i in range(count):
        open_price = price
        close = price * 1.001
        rows.append({
            "open": open_price,
            "high": close * 1.002,
            "low": open_price * 0.998,
            "close": close,
            "volume": 1000.0,
            "date": (start + timedelta(days=i)).date().isoformat(),
            "_close_time": start + timedelta(days=i + 1),
        })
        price = close
    return rows


class BreakoutRetestResearchTests(unittest.TestCase):
    def test_retest_research_returns_separate_exploration_and_holdout(self):
        result = evaluate(_candles())
        self.assertEqual(result["method"], "daily_breakout_retest_next_open")
        self.assertIn("exploration", result)
        self.assertIn("holdout", result)
        self.assertEqual(result["exploration"]["sample_status"], "small_sample")
        self.assertEqual(result["holdout"]["sample_status"], "small_sample")
        self.assertTrue(result["limitations"])

    def test_retest_window_must_be_positive(self):
        with self.assertRaises(ValueError):
            evaluate(_candles(), retest_window=0)


if __name__ == "__main__":
    unittest.main()
