import unittest
from unittest.mock import Mock

from global_markets.crypto_feed import CryptoWatchlistFeed
from global_markets.providers.binance import BinanceMarketDataError


class CryptoWatchlistFeedTests(unittest.TestCase):
    def test_fetches_daily_and_four_hour_bars_for_active_pair(self):
        client = Mock()
        client.get_spot_symbol_status.return_value = {
            "BTCUSDT": {"status": "TRADING", "spot_allowed": True}
        }
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            [{"symbol": "BTCUSDT", "interval": "4h", "close": 101.0}],
        ]
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        self.assertEqual(result["source"], "binance")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["summary"]["observations"], 2)
        self.assertEqual([x["interval"] for x in result["data"]], ["1d", "4h"])

    def test_reports_unmapped_symbol_for_each_interval(self):
        client = Mock()
        client.get_spot_symbol_status.return_value = {}
        result = CryptoWatchlistFeed(client).fetch(symbols=["UNKNOWNUSD"])
        client.get_klines.assert_not_called()
        self.assertEqual(result["summary"]["unavailable_requests"], 2)
        self.assertEqual(result["summary"]["availability_counts"]["no_binance_pair_mapping"], 2)

    def test_distinguishes_missing_inactive_and_spot_restricted_pairs(self):
        client = Mock()
        client.get_spot_symbol_status.return_value = {
            "XMRUSDT": {"status": "BREAK", "spot_allowed": True},
            "ANVLUSDT": {"status": "TRADING", "spot_allowed": False},
        }
        result = CryptoWatchlistFeed(client).fetch(symbols=["XMRUSD", "ANVLUSD", "LEOUSD"])
        self.assertEqual(
            {item["reason"] for item in result["unavailable"]},
            {"pair_not_trading_on_binance_spot", "spot_trading_not_allowed_for_pair",
             "pair_not_listed_on_binance_spot"},
        )
        self.assertEqual(result["summary"]["availability_counts"]["pair_not_listed_on_binance_spot"], 2)
        client.get_klines.assert_not_called()

    def test_fails_closed_when_spot_listing_check_fails(self):
        client = Mock()
        client.get_spot_symbol_status.side_effect = BinanceMarketDataError("temporary")
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        client.get_klines.assert_not_called()
        self.assertEqual(result["data"], [])
        self.assertEqual(result["summary"]["availability_counts"]["spot_listing_check_failed"], 2)

    def test_provider_errors_are_classified_and_partial_data_kept(self):
        client = Mock()
        client.get_spot_symbol_status.return_value = {
            "BTCUSDT": {"status": "TRADING", "spot_allowed": True}
        }
        client.get_klines.side_effect = [
            [{"symbol": "BTCUSDT", "interval": "1d", "close": 100.0}],
            BinanceMarketDataError("Binance public market-data rate limit reached"),
        ]
        result = CryptoWatchlistFeed(client).fetch(symbols=["BTCUSD"])
        self.assertEqual(result["summary"]["observations"], 1)
        self.assertEqual(result["summary"]["availability_counts"]["rate_limit"], 1)
        self.assertEqual(result["unavailable"][0]["detail"],
                         "Binance public market-data rate limit reached")


if __name__ == "__main__":
    unittest.main()
