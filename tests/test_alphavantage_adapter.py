import unittest
from unittest.mock import Mock

from global_markets.providers.alphavantage import AlphaVantageClient, AlphaVantageError


class AlphaVantageClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = AlphaVantageClient("test-key", session=self.session)

    def response(self, payload):
        response = Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_fx_daily_normalizes_provider_series(self):
        self.session.get.return_value = self.response({
            "Time Series FX (Daily)": {
                "2026-10-30": {
                    "1. open": "1.16", "2. high": "1.17",
                    "3. low": "1.15", "4. close": "1.165",
                }
            }
        })
        rows = self.client.get_fx_daily("EUR", "USD")
        self.assertEqual(rows[0]["symbol"], "EURUSD")
        self.assertEqual(rows[0]["close"], 1.165)
        self.assertEqual(rows[0]["source"], "alpha_vantage")

    def test_crypto_daily_normalizes_usd_fields(self):
        self.session.get.return_value = self.response({
            "Time Series (Digital Currency Daily)": {
                "2026-10-30": {
                    "1a. open (USD)": "100", "2a. high (USD)": "110",
                    "3a. low (USD)": "90", "4a. close (USD)": "105",
                }
            }
        })
        rows = self.client.get_crypto_daily("BTC")
        self.assertEqual(rows[0]["symbol"], "BTCUSD")
        self.assertEqual(rows[0]["close"], 105.0)

    def test_detects_soft_rate_limit(self):
        self.session.get.return_value = self.response({"Note": "quota reached"})
        with self.assertRaisesRegex(AlphaVantageError, "rate limit"):
            self.client.get_fx_daily("EUR", "USD")

    def test_rejects_missing_key(self):
        with self.assertRaises(ValueError):
            AlphaVantageClient(" ")


if __name__ == "__main__":
    unittest.main()
