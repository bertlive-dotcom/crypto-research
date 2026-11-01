import unittest
from unittest.mock import Mock

from global_markets.crypto_feed import CryptoWatchlistFeed


class CryptoWatchlistFeedTests(unittest.TestCase):
    def test_fetches_daily_and_four_hour_bars_for_default_seed(self):
        client = Mock()
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            [{"symbol": "BTCUSDT", "interval": "4h", "close": 101.0}],
        ]
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        self.assertEqual(result["source"], "binance")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["summary"]["observations"], 2)
        self.assertEqual([x["interval"] for x in result["data"]], ["1d", "4h"])

    def test_reports_unmapped_symbol_without_request(self):
        client = Mock()
        result = CryptoWatchlistFeed(client).fetch(symbols=["UNKNOWNUSD"])
        client.get_klines.assert_not_called()
        self.assertEqual(result["summary"]["unavailable_requests"], 1)
        self.assertEqual(result["unavailable"][0]["reason"], "no_binance_pair_mapping")

    def test_keeps_partial_results_when_pair_is_unavailable(self):
        client = Mock()
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            RuntimeError("unexpected"),
        ]
        # RuntimeError is intentionally not swallowed; provider errors are typed.
        with self.assertRaises(RuntimeError):
            CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])

    def test_reports_provider_pair_error_and_continues(self):
        from global_markets.providers.binance import BinanceMarketDataError
        client = Mock()
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            BinanceMarketDataError("pair unavailable"),
        ]
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        self.assertEqual(result["summary"]["observations"], 1)
        self.assertEqual(result["summary"]["unavailable_requests"], 1)


if __name__ == "__main__":
    unittest.main()
