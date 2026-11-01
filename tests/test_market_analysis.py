import unittest
from datetime import datetime, timedelta, timezone

from global_markets.market_analysis import analyze_candles, analyze_feed


class MarketAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    def rows(self, count=60, interval="1d", close_time=None):
        rows = []
        end = close_time or self.now - timedelta(minutes=1)
        step = timedelta(hours=4) if interval == "4h" else timedelta(days=1)
        for i in range(count):
            close = 100 + i * 0.5
            timestamp = end - step * (count - 1 - i)
            rows.append({
                "symbol": "BTCUSDT", "interval": interval, "source": "binance",
                "timestamp": (timestamp - step).isoformat(),
                "close_timestamp": timestamp.isoformat(),
                "open": close - 0.2, "high": close + 0.5,
                "low": close - 0.5, "close": close, "volume": 10.0,
            })
        return rows

    def test_fresh_daily_series_has_indicators_and_technical_score(self):
        result = analyze_candles(self.rows(), now=self.now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["status"], "fresh")
        self.assertIsNotNone(result["indicators"]["rsi_14"])
        self.assertIsNotNone(result["indicators"]["macd_12_26"])
        self.assertIsNotNone(result["indicators"]["sma_20"])
        self.assertEqual(result["score_type"], "technical_only_not_investment_recommendation")

    def test_rejects_stale_xmr_like_history(self):
        old = self.rows(close_time=self.now - timedelta(days=30))
        result = analyze_candles(old, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("stale_market_data", result["reasons"])

    def test_rejects_insufficient_history(self):
        result = analyze_candles(self.rows(count=10), now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("insufficient_history", result["reasons"])

    def test_rejects_future_open_time(self):
        future = self.rows(close_time=self.now + timedelta(hours=2))
        future[-1]["timestamp"] = (self.now + timedelta(hours=1)).isoformat()
        result = analyze_candles(future, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("future_candle", result["reasons"])

    def test_ignores_current_unclosed_daily_candle(self):
        rows = self.rows()
        rows.append({
            "symbol": "BTCUSDT", "interval": "1d", "source": "binance",
            "timestamp": (self.now + timedelta(seconds=1)).isoformat(),
            "close_timestamp": (self.now + timedelta(days=1)).isoformat(),
            "open": 100.0, "high": 10000.0, "low": 90.0,
            "close": 9999.0, "volume": 1000.0,
        })
        result = analyze_candles(rows, now=self.now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["bars"], 60)
        self.assertEqual(result["latest_close"], 129.5)

    def test_feed_analysis_keeps_provider_unavailable_pairs(self):
        result = analyze_feed({
            "source": "binance", "data": self.rows(),
            "unavailable": [{"symbol": "LEOUSD", "reason": "not_listed"}],
        }, now=self.now)
        self.assertEqual(result["eligible_series"], 1)
        self.assertEqual(result["provider_unavailable"][0]["symbol"], "LEOUSD")


if __name__ == "__main__":
    unittest.main()
