import unittest
from datetime import datetime, timedelta, timezone

from assistant.market_data import validate_daily_series


def bars(days=45):
    rows = []
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for index in range(days):
        opened = start + timedelta(days=index)
        closed = opened + timedelta(hours=23, minutes=59)
        close = 100 + index
        rows.append({
            "symbol": "SPY", "asset_class": "etf", "source": "twelve_data",
            "interval": "1d", "timestamp": opened.isoformat(),
            "close_timestamp": closed.isoformat(), "open": close - 0.5,
            "high": close + 1, "low": close - 1, "close": close,
        })
    return rows


class DailySeriesValidationTests(unittest.TestCase):
    def validate(self, rows):
        return validate_daily_series(
            rows, symbol="SPY", asset_class="etf", source="twelve_data"
        )

    def test_accepts_consistent_daily_history(self):
        result = self.validate(bars())
        self.assertTrue(result["usable"])
        self.assertEqual(result["bars"], 45)

    def test_rejects_duplicate_dates_and_non_increasing_timestamps(self):
        rows = bars()
        rows[10] = dict(rows[9])
        result = self.validate(rows)
        self.assertFalse(result["usable"])
        self.assertTrue(any("duplicate_observation_date" in reason for reason in result["reasons"]))

    def test_rejects_large_history_gap(self):
        rows = bars()
        rows[20]["timestamp"] = (datetime.fromisoformat(rows[20]["timestamp"]) + timedelta(days=10)).isoformat()
        rows[20]["close_timestamp"] = (datetime.fromisoformat(rows[20]["close_timestamp"]) + timedelta(days=10)).isoformat()
        for index in range(20, len(rows)):
            rows[index]["timestamp"] = (datetime.fromisoformat(rows[index]["timestamp"]) + timedelta(days=10)).isoformat()
            rows[index]["close_timestamp"] = (datetime.fromisoformat(rows[index]["close_timestamp"]) + timedelta(days=10)).isoformat()
        result = self.validate(rows)
        self.assertFalse(result["usable"])
        self.assertTrue(any("history_gap_over_7_days" in reason for reason in result["reasons"]))

    def test_rejects_mixed_source_symbol_and_bad_ohlc(self):
        rows = bars()
        rows[5]["source"] = "financialdata.net"
        rows[6]["symbol"] = "VOO"
        rows[7]["high"] = rows[7]["low"] - 1
        result = self.validate(rows)
        self.assertFalse(result["usable"])
        self.assertTrue(any("source_mismatch" in reason for reason in result["reasons"]))
        self.assertTrue(any("symbol_mismatch" in reason for reason in result["reasons"]))
        self.assertTrue(any("inconsistent_ohlc" in reason for reason in result["reasons"]))

    def test_rejects_naive_timestamps(self):
        rows = bars()
        rows[0]["timestamp"] = "2026-09-01T00:00:00"
        result = self.validate(rows)
        self.assertFalse(result["usable"])
        self.assertTrue(any("malformed_daily_candle" in reason for reason in result["reasons"]))


if __name__ == "__main__":
    unittest.main()
