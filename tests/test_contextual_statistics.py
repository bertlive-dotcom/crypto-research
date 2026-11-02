import unittest
from datetime import datetime, timedelta, timezone

from global_markets.contextual_statistics import analyze_context, closed_hourly_candles


class ContextualStatisticsTests(unittest.TestCase):
    def rows(self, count=500):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        price = 100.0
        for i in range(count):
            opened = price
            price *= 1.0002 if i % 3 else 0.9998
            rows.append({
                "symbol": "BTCUSDT",
                "timestamp": (start + timedelta(hours=i)).isoformat(),
                "close_timestamp": (start + timedelta(hours=i+1)).isoformat(),
                "open": opened, "high": max(opened, price)*1.001,
                "low": min(opened, price)*0.999, "close": price,
                "volume": 100.0,
            })
        return rows

    def test_excludes_unclosed_and_invalid_rows(self):
        rows = self.rows()
        rows.append({**rows[-1], "timestamp": "2026-02-01T00:00:00+00:00",
                     "close_timestamp": "2026-02-01T01:00:00+00:00"})
        rows[-2]["low"] = rows[-2]["high"] + 1
        cleaned = closed_hourly_candles(rows, now=datetime(2026, 1, 22, tzinfo=timezone.utc))
        self.assertEqual(len(cleaned), 499)

    def test_reports_context_dimensions_and_holdout(self):
        report = analyze_context(self.rows(), now=datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(report["interval"], "1h")
        self.assertEqual(report["closed_candles"], 500)
        self.assertEqual(set(report["dimensions"]), {
            "utc_hour", "utc_weekday", "trend_regime",
            "volatility_regime", "combined_regime",
        })
        self.assertIn("holdout", report["dimensions"]["utc_hour"]["00:00"]["1"])
        self.assertIn("matched_baseline_mean_pct",
                      report["dimensions"]["utc_hour"]["00:00"]["1"]["holdout"])

    def test_invalid_horizon_rejected(self):
        with self.assertRaises(ValueError):
            analyze_context(self.rows(), horizons=(0,))


if __name__ == "__main__":
    unittest.main()
