import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from global_markets.providers.twelvedata import TwelveDataClient, TwelveDataError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return self.response


class TwelveDataETFAdapterTests(unittest.TestCase):
    def payload(self):
        return {
            "meta": {
                "symbol": "SPY", "type": "ETF",
                "exchange_timezone": "America/New_York",
                "exchange": "NYSE Arca",
            },
            "values": [{
                "datetime": "2026-11-12", "open": "680", "high": "685",
                "low": "678", "close": "684", "volume": "1000000",
            }],
            "status": "ok",
        }

    def test_normalizes_etf_daily_bar_using_exchange_timezone_and_close(self):
        session = FakeSession(FakeResponse(payload=self.payload()))
        client = TwelveDataClient("test-key", session=session)
        result = client.fetch_daily_prices_with_quality("SPY", "etf", limit=120)
        candle = result["candles"][0]
        ny = ZoneInfo("America/New_York")
        expected_open = datetime(2026, 11, 12, 0, 0, tzinfo=ny)
        expected_close = datetime(2026, 11, 12, 16, 0, tzinfo=ny)
        self.assertEqual(candle["timestamp"], expected_open.astimezone().astimezone(__import__("datetime").timezone.utc).isoformat())
        self.assertEqual(candle["close_timestamp"], expected_close.astimezone(__import__("datetime").timezone.utc).isoformat())
        self.assertEqual(candle["source"], "twelve_data")
        self.assertEqual(session.calls[0][1]["interval"], "1day")
        self.assertEqual(session.calls[0][1]["symbol"], "SPY")
        self.assertEqual(session.calls[0][1]["outputsize"], 120)
        self.assertEqual(result["rejected_records"], [])

    def test_rejects_non_etf_metadata_and_wrong_symbol(self):
        payload = self.payload()
        payload["meta"]["type"] = "Common Stock"
        client = TwelveDataClient("test-key", session=FakeSession(FakeResponse(payload=payload)))
        with self.assertRaisesRegex(TwelveDataError, "does not identify"):
            client.fetch_daily_prices_with_quality("SPY", "etf")

        payload = self.payload()
        payload["meta"]["symbol"] = "VOO"
        client = TwelveDataClient("test-key", session=FakeSession(FakeResponse(payload=payload)))
        with self.assertRaisesRegex(TwelveDataError, "different symbol"):
            client.fetch_daily_prices_with_quality("SPY", "etf")

    def test_reports_authorization_and_quota_errors_without_credentials(self):
        for status, expected in ((401, "HTTP 401"), (403, "HTTP 403"), (429, "HTTP 429")):
            client = TwelveDataClient("super-secret", session=FakeSession(FakeResponse(status_code=status)))
            with self.assertRaises(TwelveDataError) as caught:
                client.fetch_daily_prices_with_quality("SPY", "etf")
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn("super-secret", str(caught.exception))

    def test_rejects_invalid_ohlc_and_duplicate_days(self):
        payload = self.payload()
        payload["values"] = [
            {"datetime": "2026-11-12", "open": "680", "high": "670", "low": "678", "close": "684"},
            {"datetime": "2026-11-12", "open": "680", "high": "685", "low": "678", "close": "684"},
        ]
        client = TwelveDataClient("test-key", session=FakeSession(FakeResponse(payload=payload)))
        result = client.fetch_daily_prices_with_quality("SPY", "etf")
        self.assertEqual(len(result["candles"]), 1)
        self.assertEqual(len(result["rejected_records"]), 1)

    def test_rejects_wrong_asset_class_and_small_history(self):
        client = TwelveDataClient("test-key", session=FakeSession(FakeResponse(payload=self.payload())))
        with self.assertRaises(ValueError):
            client.fetch_daily_prices_with_quality("NVDA", "equity")
        with self.assertRaises(ValueError):
            client.fetch_daily_prices_with_quality("SPY", "etf", limit=10)


if __name__ == "__main__":
    unittest.main()
