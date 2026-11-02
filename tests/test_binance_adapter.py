import unittest
from unittest.mock import Mock

from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError


class BinanceMarketDataClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = BinanceMarketDataClient(session=self.session)

    def response(self, payload):
        response = Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_exchange_info_returns_only_active_spot_symbols(self):
        self.session.get.return_value = self.response({"symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "XMRUSDT", "status": "BREAK", "isSpotTradingAllowed": True},
            {"symbol": "ANVLUSDT", "status": "TRADING", "isSpotTradingAllowed": False},
        ]})
        self.assertEqual(self.client.get_active_spot_symbols(), {"BTCUSDT"})

    def test_normalizes_daily_candle(self):
        self.session.get.return_value = self.response([[
            1793318400000, "100", "110", "90", "105", "12.5",
            1793404799999, "1300", 42, "6", "630", "0"
        ]])
        row = self.client.get_klines("btcusdt")[0]
        self.assertEqual(row["symbol"], "BTCUSDT")
        self.assertEqual(row["asset_class"], "crypto")
        self.assertEqual(row["close"], 105.0)
        self.assertEqual(row["volume"], 12.5)
        self.assertEqual(row["source"], "binance")
        self.assertEqual(row["interval"], "1d")

    def test_rejects_invalid_symbol(self):
        with self.assertRaises(ValueError):
            self.client.get_klines("BTC/USDT")

    def test_rejects_limit_out_of_range(self):
        with self.assertRaises(ValueError):
            self.client.get_klines("BTCUSDT", limit=1001)

    def test_rejects_empty_response(self):
        self.session.get.return_value = self.response([])
        with self.assertRaisesRegex(BinanceMarketDataError, "no kline"):
            self.client.get_klines("BTCUSDT")


    def test_paginated_history_returns_sorted_deduplicated_rows(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch

        origin = datetime(2020, 1, 1, tzinfo=timezone.utc)
        def row(index):
            stamp = origin + timedelta(days=index)
            return {"timestamp": stamp.isoformat(), "date": stamp.date().isoformat(),
                    "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}

        newest_page = [row(i) for i in range(500, 1500)]
        older_page = [row(i) for i in range(0, 500)]
        with patch.object(self.client, "get_klines",
                          side_effect=[newest_page, older_page]) as mocked:
            result = self.client.get_klines_history("BTCUSDT", total_limit=1500)

        self.assertEqual(len(result), 1500)
        self.assertEqual(result[0]["date"], "2020-01-01")
        self.assertEqual(result[-1]["date"], "2024-02-09")
        self.assertEqual(mocked.call_count, 2)
        self.assertIsNone(mocked.call_args_list[0].kwargs["end_time_ms"])
        self.assertIsNotNone(mocked.call_args_list[1].kwargs["end_time_ms"])

    def test_paginated_history_rejects_oversized_limit(self):
        with self.assertRaises(ValueError):
            self.client.get_klines_history("BTCUSDT", total_limit=10001)


if __name__ == "__main__":
    unittest.main()
