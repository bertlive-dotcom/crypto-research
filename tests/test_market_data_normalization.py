import unittest
from datetime import datetime, timezone

from market_data_worker.normalization import normalize_candle


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def candle(**overrides):
    row = {
        "symbol": "btcusdt",
        "source": "BINANCE",
        "asset_class": "crypto",
        "interval": "1h",
        "timestamp": "2026-11-14T10:00:00Z",
        "close_timestamp": "2026-11-14T10:59:59Z",
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "volume": 12.5,
    }
    row.update(overrides)
    return row


class NormalizeCandleTests(unittest.TestCase):
    def test_normalizes_identity_and_utc(self):
        result = normalize_candle(candle(), now=NOW)
        self.assertEqual(result["symbol"], "BTCUSDT")
        self.assertEqual(result["source"], "binance")
        self.assertEqual(result["timestamp"], "2026-11-14T10:00:00+00:00")
        self.assertTrue(result["is_closed"])
        self.assertTrue(result["volume_available"])

    def test_keeps_missing_volume_missing(self):
        result = normalize_candle(candle(volume=None), now=NOW)
        self.assertIsNone(result["volume"])
        self.assertFalse(result["volume_available"])

    def test_marks_forming_candle_not_closed(self):
        result = normalize_candle(
            candle(close_timestamp="2026-11-14T12:05:00Z"), now=NOW
        )
        self.assertFalse(result["is_closed"])

    def test_rejects_naive_timestamps(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            normalize_candle(candle(timestamp="2026-11-14T10:00:00"), now=NOW)

    def test_rejects_future_open_timestamp(self):
        with self.assertRaisesRegex(ValueError, "future"):
            normalize_candle(candle(timestamp="2026-11-14T12:01:00Z"), now=NOW)

    def test_rejects_inconsistent_ohlc(self):
        with self.assertRaisesRegex(ValueError, "high is inconsistent"):
            normalize_candle(candle(high=104.0), now=NOW)

    def test_rejects_negative_volume(self):
        with self.assertRaisesRegex(ValueError, "negative"):
            normalize_candle(candle(volume=-1), now=NOW)

    def test_rejects_non_finite_price(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            normalize_candle(candle(close=float("nan")), now=NOW)

    def test_requires_source_and_instrument_metadata(self):
        with self.assertRaisesRegex(ValueError, "source/provider"):
            normalize_candle(candle(source=""), now=NOW)


if __name__ == "__main__":
    unittest.main()
