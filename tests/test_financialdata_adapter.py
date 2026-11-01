import unittest
from unittest.mock import Mock

import requests

from global_markets.providers.financialdata import FinancialDataClient, FinancialDataError


class FinancialDataClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = FinancialDataClient(
            "test-key", session=self.session, max_retries=1,
            backoff_seconds=0, sleep=lambda _: None, random_fn=lambda: 0,
        )

    def response(self, status=200, payload=None, headers=None):
        response = Mock()
        response.status_code = status
        response.headers = headers or {}
        response.json.return_value = payload
        return response

    def test_get_uses_timeout_and_api_key(self):
        self.session.get.return_value = self.response(payload=[{"trading_symbol": "AAPL"}])
        result = self.client.get("stock-symbols", {"offset": 0})
        self.assertEqual(result[0]["trading_symbol"], "AAPL")
        args, kwargs = self.session.get.call_args
        self.assertIn("stock-symbols", args[0])
        self.assertEqual(kwargs["timeout"], 10.0)
        self.assertEqual(kwargs["params"]["key"], "test-key")

    def test_retries_rate_limit_then_succeeds(self):
        self.session.get.side_effect = [
            self.response(status=429, headers={"Retry-After": "0"}),
            self.response(payload=[]),
        ]
        self.assertEqual(self.client.get("stock-symbols"), [])
        self.assertEqual(self.session.get.call_count, 2)

    def test_bounds_network_retries(self):
        self.session.get.side_effect = requests.Timeout("timeout")
        with self.assertRaises(FinancialDataError):
            self.client.get("stock-symbols")
        self.assertEqual(self.session.get.call_count, 2)

    def test_rejects_unapproved_endpoint(self):
        with self.assertRaises(ValueError):
            self.client.get("https://example.com")

    def test_symbol_match_is_exact(self):
        self.session.get.return_value = self.response(payload=[
            {"trading_symbol": "BTCUSD"}, {"trading_symbol": "ETHUSD"},
        ])
        result = self.client.find_symbols("crypto", ["BTCUSD", "HYPEUSD"])
        self.assertIsNotNone(result["BTCUSD"])
        self.assertIsNone(result["HYPEUSD"])

    def test_normalizes_crypto_quote_and_preserves_source_time(self):
        quote = FinancialDataClient.normalize_quote({
            "trading_symbol": "BTCUSD", "price": 65000,
            "time": "2026-11-01 12:00:00",
        }, asset_class="crypto")
        self.assertEqual(quote["symbol"], "BTCUSD")
        self.assertEqual(quote["source_timestamp"], "2026-11-01 12:00:00")
        self.assertTrue(quote["observed_at"].endswith("+00:00"))

    def test_rejects_non_finite_quote_prices(self):
        for price in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(price=price):
                with self.assertRaises(FinancialDataError):
                    FinancialDataClient.normalize_quote(
                        {"trading_symbol": "BTCUSD", "price": price,
                         "time": "2026-11-01 12:00:00"},
                        asset_class="crypto",
                    )

    def test_rejects_non_finite_timeout(self):
        with self.assertRaises(ValueError):
            FinancialDataClient("test-key", timeout=float("nan"))

    def test_rejects_bad_quote(self):
        with self.assertRaises(FinancialDataError):
            FinancialDataClient.normalize_quote(
                {"trading_symbol": "BTCUSD", "price": 0, "time": "2026-11-01 12:00:00"},
                asset_class="crypto",
            )

    def test_fetch_daily_prices_normalizes_exact_symbol_and_sorts_oldest_first(self):
        self.session.get.return_value = self.response(payload=[
            {"trading_symbol": "MSFT", "date": "2026-10-30", "open": 10,
             "high": 12, "low": 9, "close": 11, "volume": 100},
            {"trading_symbol": "OTHER", "date": "2026-10-31", "open": 1,
             "high": 2, "low": 1, "close": 2, "volume": 20},
            {"trading_symbol": "MSFT", "date": "2026-10-29", "open": 9,
             "high": 11, "low": 8, "close": 10, "volume": 90},
        ])
        rows = self.client.fetch_daily_prices("MSFT", "equity")
        self.assertEqual([row["date"] for row in rows], ["2026-10-29", "2026-10-30"])
        self.assertEqual(rows[-1]["interval"], "1d")
        self.assertEqual(rows[-1]["source"], "financialdata.net")

    def test_fetch_daily_prices_rejects_bad_ohlc(self):
        self.session.get.return_value = self.response(payload=[
            {"trading_symbol": "GC", "date": "2026-10-30", "open": 10,
             "high": 8, "low": 9, "close": 11, "volume": 100},
        ])
        with self.assertRaises(FinancialDataError):
            self.client.fetch_daily_prices("GC", "commodity")

    def test_fetch_daily_prices_uses_international_equity_endpoint(self):
        self.session.get.return_value = self.response(payload=[
            {"trading_symbol": "SU.PA", "date": "2026-10-30", "open": 10,
             "high": 12, "low": 9, "close": 11, "volume": 100},
        ])
        self.client.fetch_daily_prices("SU.PA", "equity", international=True)
        args, _ = self.session.get.call_args
        self.assertIn("international-stock-prices", args[0])

    def test_fetch_daily_prices_rejects_unsupported_class_and_limit(self):
        with self.assertRaises(ValueError):
            self.client.fetch_daily_prices("EURUSD", "forex")
        with self.assertRaises(ValueError):
            self.client.fetch_daily_prices("MSFT", "equity", limit=301)

    def test_http_401_reports_endpoint_access_or_entitlement(self):
        self.session.get.return_value = self.response(status=401)
        with self.assertRaisesRegex(FinancialDataError, "access denied.*endpoint plan entitlement"):
            self.client.get("etf-prices")

    def test_bad_commodity_ohlc_error_includes_provider_values(self):
        self.session.get.return_value = self.response(payload=[
            {"trading_symbol": "GC", "date": "2026-10-30", "open": 10,
             "high": 8, "low": 9, "close": 11, "volume": 100},
        ])
        with self.assertRaisesRegex(FinancialDataError, "no valid exact-symbol records"):
            self.client.fetch_daily_prices_with_quality("GC", "commodity")


    def test_daily_quality_skips_bad_rows(self):
        self.session.get.return_value = self.response(payload=[
            {"trading_symbol": "GC", "date": "2026-10-30", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"trading_symbol": "GC", "date": "2026-10-29", "open": 10, "high": 8, "low": 9, "close": 11, "volume": 100},
        ])
        result = self.client.fetch_daily_prices_with_quality("GC", "commodity")
        self.assertEqual(len(result["candles"]), 1)
        self.assertEqual(len(result["rejected_records"]), 1)

if __name__ == "__main__":
    unittest.main()
