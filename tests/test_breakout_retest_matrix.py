import unittest

from tools.run_breakout_retest_matrix import _stats, _classify


class BreakoutRetestMatrixTests(unittest.TestCase):
    def test_stats_preserve_small_sample_warning_and_net_returns(self):
        result = _stats([
            {"net_return_pct": 2.0},
            {"net_return_pct": -1.0},
            {"net_return_pct": 0.5},
        ])
        self.assertEqual(result["trades"], 3)
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["win_rate_pct"], 66.7)
        self.assertEqual(result["sample_status"], "small_sample")
        self.assertEqual(result["profit_factor"], 2.5)

    def test_regime_labels_are_keyed_by_exact_timestamp(self):
        candles = []
        for i in range(220):
            close = 100 + i
            candles.append({
                "timestamp": f"2026-01-{(i // 6) + 1:02d}T{(i % 6) * 4:02d}:00:00+00:00",
                "date": "2026-01-01",
                "close": float(close),
            })
        labels = _classify(candles)
        self.assertEqual(len(labels), 220)
        self.assertIn("2026-01-01T00:00:00+00:00", labels)
        self.assertIn("2026-01-01T20:00:00+00:00", labels)


if __name__ == "__main__":
    unittest.main()
