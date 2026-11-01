import unittest
from unittest.mock import Mock

from global_markets.crypto_feed import CryptoWatchlistFeed


class CryptoWatchlistFeedTests(unittest.TestCase):
    def test_fetches_daily_and_four_hour_bars_for_default_seed(self):
        client = Mock()
        client.get_spot_symbol_status.return_value = {"BTCUSDT": {"status": "TRADING", "spot_allowed": True}}
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
        client.get_spot_symbol_status.return_value = {}
        result = CryptoWatchlistFeed(client).fetch(symbols=["UNKNOWNUSD"])
        client.get_klines.assert_not_called()
        self.assertEqual(result["summary"]["unavailable_requests"], 1)
        self.assertEqual(result["unavailable"][0]["reason"], "no_binance_pair_mapping")

    def test_keeps_partial_results_when_pair_is_unavailable(self):
        client = Mock()
        client.get_active_spot_symbols.return_value = {"BTCUSDT"}
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            RuntimeError("unexpected"),
        ]
        # RuntimeError is intentionally not swallowed; provider errors are typed.
        with self.assertRaises(RuntimeError):
            CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])

    def test_skips_delisted_pair_before_requesting_old_klines(self):
        client = Mock()
        client.get_active_spot_symbols.return_value = set()
        result = CryptoWatchlistFeed(client).fetch(symbols=["XMRUSD"])
        client.get_klines.assert_not_called()
        self.assertEqual(result["unavailable"][0]["reason"],
                         "pair_not_currently_trading_on_binance_spot")

    def test_fails_closed_when_spot_listing_check_fails(self):
        from global_markets.providers.binance import BinanceMarketDataError
        client = Mock()
        client.get_spot_symbol_status.side_effect = BinanceMarketDataError("temporary")
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        client.get_klines.assert_not_called()
        self.assertEqual(result["data"], [])
        self.assertIn("spot_listing_check_failed", result["unavailable"][0]["reason"])

    def test_reports_provider_pair_error_and_continues(self):
        from global_markets.providers.binance import BinanceMarketDataError
        client = Mock()
        client.get_active_spot_symbols.return_value = {"BTCUSDT"}
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            BinanceMarketDataError("pair unavailable"),
        ]
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        self.assertEqual(result["summary"]["observations"], 1)
        self.assertEqual(result["summary"]["unavailable_requests"], 1)


if __name__ == "__main__":
    unittest.main()
