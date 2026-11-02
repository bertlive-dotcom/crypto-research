import unittest
from datetime import datetime, timedelta, timezone

from global_markets.statistical_intelligence import analyze_pattern_history, closed_candles


class StatisticalIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)

    def rows(self, count=80):
        rows = []
        for index in range(count):
            close = 100 + index * 0.25
            opened = close - 0.1
            rows.append({
                "symbol": "BTCUSDT", "interval": "1d",
                "date": (self.now - timedelta(days=count-index)).date().isoformat(),
                "timestamp": (self.now - timedelta(days=count-index+1)).isoformat(),
                "close_timestamp": (self.now - timedelta(days=count-index)).isoformat(),
                "open": opened, "high": close + 0.3, "low": opened - 0.3,
                "close": close, "volume": 100,
            })
        return rows

    def test_unclosed_candles_are_excluded(self):
        rows = self.rows()
        rows.append({
            "symbol": "BTCUSDT", "interval": "1d",
            "timestamp": self.now.isoformat(),
            "close_timestamp": (self.now + timedelta(days=1)).isoformat(),
            "open": 120, "high": 130, "low": 110, "close": 125,
        })
        self.assertEqual(len(closed_candles(rows, now=self.now)), 80)

    def test_report_contains_all_patterns_and_metadata(self):
        report = analyze_pattern_history(self.rows(), now=self.now)
        self.assertEqual(report["symbol"], "BTCUSDT")
        self.assertEqual(report["closed_candles"], 80)
        self.assertEqual(set(report["patterns"]), {
            "inside_bar", "bullish_engulfing", "bearish_engulfing",
            "prior_day_range_breakout_up", "prior_day_range_breakout_down",
        })
        self.assertIn("limitations", report)
        self.assertIn("volatility_regime_analysis", report)
        self.assertEqual(
            set(report["combined_regime_analysis"]["inside_bar"]),
            {
                "bullish_high_volatility", "bullish_low_volatility",
                "bearish_high_volatility", "bearish_low_volatility",
                "sideways_or_transition_high_volatility",
                "sideways_or_transition_low_volatility",
            },
        )

    def test_direction_adjusted_breakout_return_is_positive_in_uptrend(self):
        rows = self.rows()
        for row in rows:
            row["high"] = row["close"] + 0.05
        report = analyze_pattern_history(rows, now=self.now, min_sample=1)
        breakout = report["patterns"]["prior_day_range_breakout_up"]
        self.assertGreater(breakout["horizons"]["1"]["mean_forward_return_pct"], 0)
        self.assertEqual(breakout["horizons"]["1"]["sample_status"], "usable_for_exploration")

    def test_small_sample_is_flagged(self):
        report = analyze_pattern_history(self.rows(count=10), now=self.now, min_sample=30)
        pattern = report["patterns"]["prior_day_range_breakout_up"]
        self.assertEqual(pattern["horizons"]["1"]["sample_status"], "small_sample")

    def test_regime_analysis_includes_matched_baseline(self):
        rows = self.rows()
        for row in rows:
            row["high"] = row["close"] + 0.05
        report = analyze_pattern_history(rows, now=self.now, min_sample=1)
        breakout = report["regime_analysis"]["prior_day_range_breakout_up"]["bullish"]["1"]
        self.assertGreater(breakout["observations"], 0)
        self.assertIsNotNone(breakout["matched_baseline_mean_return_pct"])
        self.assertIsNotNone(breakout["excess_vs_baseline_pct_points"])

    def test_volatility_regimes_use_trailing_history_only(self):
        from global_markets.statistical_intelligence import _volatility_regimes
        rows = self.rows(count=300)
        labels = _volatility_regimes(rows)
        self.assertIsNone(labels[199])
        self.assertIn(labels[200], ("high_volatility", "low_volatility"))
        self.assertEqual(len(labels), 300)

    def test_combined_regime_comparison_uses_matched_six_scenario_matrix(self):
        rows = self.rows(count=300)
        for row in rows:
            row["high"] = row["close"] + 0.05
        report = analyze_pattern_history(rows, now=self.now, min_sample=1)
        matrix = report["combined_regime_analysis"]["prior_day_range_breakout_up"]
        self.assertEqual(len(matrix), 6)
        populated = [cell for cell in matrix.values() if cell["1"]["observations"] > 0]
        self.assertTrue(populated)
        self.assertTrue(all(cell["1"]["matched_baseline_mean_return_pct"] is not None for cell in populated))

    def test_even_sample_median_is_average_of_middle_values(self):
        from global_markets.statistical_intelligence import _summarize
        events = [
            {"forward_returns_pct": {"1": value}}
            for value in (1.0, 2.0, 3.0, 4.0)
        ]
        summary = _summarize(events, (1,), 1)
        self.assertEqual(summary["horizons"]["1"]["median_forward_return_pct"], 2.5)

    def test_invalid_horizon_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze_pattern_history(self.rows(), now=self.now, horizons=(0,))

    def test_bad_ohlc_is_excluded(self):
        rows = self.rows()
        rows[0]["low"] = rows[0]["high"] + 10
        self.assertEqual(len(closed_candles(rows, now=self.now)), 79)


if __name__ == "__main__":
    unittest.main()
