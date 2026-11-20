import unittest

from scanner.ttz import analyze_price_action


def candle(open_, high, low, close, volume=100.0):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


class TTZPriceActionTests(unittest.TestCase):
    def test_insufficient_history_fails_closed(self):
        result = analyze_price_action([candle(100, 101, 99, 100)] * 4, lookback=3)
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["wick_rejection"], "NONE")

    def test_bearish_wick_rejection(self):
        rows = [
            candle(100, 102, 98, 100),
            candle(100, 102, 98, 100),
            candle(100, 102, 98, 100),
            candle(100, 102, 98, 100),
            candle(100, 110, 90, 95),
        ]
        result = analyze_price_action(rows, lookback=3)
        self.assertEqual(result["wick_rejection"], "BEARISH")

    def test_failed_high_is_detected_when_close_returns_below_range(self):
        rows = [
            candle(100, 105, 95, 100),
            candle(100, 105, 95, 100),
            candle(100, 105, 95, 100),
            candle(100, 105, 95, 100),
            candle(104, 112, 101, 104),
        ]
        result = analyze_price_action(rows, lookback=3)
        self.assertEqual(result["failed_breakout"], "FAILED_HIGH")

    def test_failed_low_is_detected_when_close_recovers_above_range(self):
        rows = [
            candle(100, 105, 95, 100),
            candle(100, 105, 95, 100),
            candle(100, 105, 95, 100),
            candle(100, 105, 95, 100),
            candle(96, 99, 88, 96),
        ]
        result = analyze_price_action(rows, lookback=3)
        self.assertEqual(result["failed_breakout"], "FAILED_LOW")

    def test_bullish_retest_requires_prior_breakout_then_revisit(self):
        rows = [
            candle(95, 100, 90, 96),
            candle(96, 100, 91, 97),
            candle(97, 100, 92, 99),
            candle(100, 106, 99, 105),
            candle(104, 106, 99.8, 104.5),
        ]
        result = analyze_price_action(rows, lookback=3)
        self.assertEqual(result["retest"], "BULLISH")

    def test_high_volume_wick_is_labeled_as_exhaustion(self):
        rows = [
            candle(100, 102, 98, 100, 100),
            candle(100, 102, 98, 100, 100),
            candle(100, 102, 98, 100, 100),
            candle(100, 102, 98, 100, 100),
            candle(100, 110, 90, 95, 300),
        ]
        result = analyze_price_action(rows, lookback=3)
        self.assertEqual(result["wick_rejection"], "BEARISH")
        self.assertEqual(result["exhaustion"], "UPSIDE")
        self.assertGreaterEqual(result["volume_ratio"], 1.5)

    def test_invalid_ohlcv_rows_are_ignored(self):
        rows = [candle(100, 102, 98, 100)] * 4 + [
            {"open": 100, "high": 90, "low": 95, "close": 100, "volume": 10}
        ]
        result = analyze_price_action(rows, lookback=3)
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")

    def test_invalid_parameters_raise(self):
        with self.assertRaises(ValueError):
            analyze_price_action([], lookback=1)
        with self.assertRaises(ValueError):
            analyze_price_action([], retest_tolerance_pct=0.05)


if __name__ == "__main__":
    unittest.main()
