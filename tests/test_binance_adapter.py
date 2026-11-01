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


if __name__ == "__main__":
    unittest.main()
