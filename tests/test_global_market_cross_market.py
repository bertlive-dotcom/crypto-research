import unittest
from datetime import datetime, timedelta, timezone

from global_markets.cross_market import analyze_cross_market, normalize_twelve_data


class CrossMarketTests(unittest.TestCase):
    def make_series(self, symbol, start, changes):
        rows = []
        price = 100.0
        for index, change in enumerate(changes):
            stamp = start + timedelta(minutes=15 * index)
            price *= 1 + change / 100.0
            rows.append({
                "symbol": symbol,
                "timestamp": stamp.isoformat(),
                "close_timestamp": (stamp + timedelta(minutes=15)).isoformat(),
                "close": price,
            })
        return rows

    def test_normalizes_twelve_data_utc_candles(self):
        payload = {"values": [
            {"datetime": "2026-11-05 14:00:00", "close": "101.5"},
            {"datetime": "2026-11-05 14:15:00", "close": "102.0"},
        ]}
        rows = normalize_twelve_data(payload, "SPY")
        self.assertEqual(rows[0]["close"], 101.5)
        self.assertEqual(rows[0]["close_timestamp"], "2026-11-05T14:15:00+00:00")

    def test_detects_synchronized_risk_off(self):
        now = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
        start = now - timedelta(minutes=15 * 12)
        moves = [-0.2] * 8 + [-0.3] * 4
        candles = {
            "BTCUSDT": self.make_series("BTCUSDT", start, moves),
            "SPY": self.make_series("SPY", start, [-0.1] * 8 + [-0.15] * 4),
            "QQQ": self.make_series("QQQ", start, [-0.12] * 8 + [-0.18] * 4),
        }
        result = analyze_cross_market(candles, now=now)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["regime"], "risk_off")

    def test_rejects_insufficient_data(self):
        now = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
        result = analyze_cross_market({"BTCUSDT": [], "SPY": [], "QQQ": []}, now=now)
        self.assertEqual(result["status"], "insufficient_data")


    def test_overnight_gap_is_not_used_as_a_one_hour_return(self):
        now = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
        first_session = [now - timedelta(hours=14) + timedelta(minutes=15 * i) for i in range(5)]
        current_session = [now - timedelta(minutes=60) + timedelta(minutes=15 * i) for i in range(4)]
        timestamps = first_session + current_session
        candles = {}
        for symbol in ("BTCUSDT", "SPY", "QQQ"):
            rows = []
            price = 100.0
            for stamp in timestamps:
                price *= 1.001
                rows.append({
                    "symbol": symbol,
                    "timestamp": stamp.isoformat(),
                    "close_timestamp": (stamp + timedelta(minutes=15)).isoformat(),
                    "close": price,
                })
            candles[symbol] = rows

        result = analyze_cross_market(candles, now=now)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["assets"]["SPY"]["return_1h_pct"])
        self.assertIsNotNone(result["assets"]["SPY"]["return_15m_pct"])
        self.assertIsNone(result["correlations"]["BTC_SPY_15m"])

    def test_does_not_use_unclosed_candles(self):
        now = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
        start = now - timedelta(minutes=15 * 8)
        candles = {
            symbol: self.make_series(symbol, start, [0.1] * 9)
            for symbol in ("BTCUSDT", "SPY", "QQQ")
        }
        result = analyze_cross_market(candles, now=now)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["common_bars"], 8)


if __name__ == "__main__":
    unittest.main()
