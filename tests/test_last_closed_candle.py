import unittest
from datetime import datetime, timezone

from global_markets.providers.binance import last_closed_candle


class LastClosedCandleTests(unittest.TestCase):
    def test_ignores_current_forming_candle(self):
        candles = [
            {"timestamp": "2026-11-02T16:42:00+00:00", "close_timestamp": "2026-11-02T16:42:59.999000+00:00", "high": 10},
            {"timestamp": "2026-11-02T16:43:00+00:00", "close_timestamp": "2026-11-02T16:43:59.999000+00:00", "high": 20},
        ]
        now = datetime.fromisoformat("2026-11-02T16:43:30+00:00")
        self.assertEqual(last_closed_candle(candles, now=now)["high"], 10)

    def test_returns_newly_closed_candle(self):
        candles = [
            {"timestamp": "2026-11-02T16:42:00+00:00", "close_timestamp": "2026-11-02T16:42:59.999000+00:00", "high": 10},
            {"timestamp": "2026-11-02T16:43:00+00:00", "close_timestamp": "2026-11-02T16:43:59.999000+00:00", "high": 20},
        ]
        now = datetime.fromisoformat("2026-11-02T16:44:01+00:00")
        self.assertEqual(last_closed_candle(candles, now=now)["high"], 20)

    def test_returns_none_when_no_candle_is_closed(self):
        candles = [{"timestamp": "2026-11-02T16:43:00+00:00", "close_timestamp": "2026-11-02T16:43:59.999000+00:00"}]
        now = datetime.fromisoformat("2026-11-02T16:43:30+00:00")
        self.assertIsNone(last_closed_candle(candles, now=now))


if __name__ == "__main__":
    unittest.main()
