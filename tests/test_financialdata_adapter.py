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


if __name__ == "__main__":
    unittest.main()
