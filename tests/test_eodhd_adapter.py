import unittest

from global_markets.providers.eodhd import EODHDClient, EODHDError


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self.payload = status_code, payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return self.response


class EODHDAdapterTests(unittest.TestCase):
    def payload(self):
        return [{
            "date": "2026-11-12", "open": 680, "high": 685,
            "low": 678, "close": 684, "adjusted_close": 684,
            "volume": 1000000,
        }]

    def test_fetches_spy_us_daily_and_normalizes_ohlcv(self):
        session = FakeSession(FakeResponse(payload=self.payload()))
        result = EODHDClient("test-token", session=session).fetch_daily_prices_with_quality("SPY.US", "etf")
        self.assertEqual(session.calls[0][0], "https://eodhd.com/api/eod/SPY.US")
        self.assertEqual(session.calls[0][1]["period"], "d")
        self.assertEqual(session.calls[0][1]["fmt"], "json")
        candle = result["candles"][0]
        self.assertEqual(candle["symbol"], "SPY.US")
        self.assertEqual(candle["source"], "eodhd")
        self.assertEqual(candle["close"], 684)
        self.assertEqual(candle["volume"], 1000000)

    def test_limit_keeps_most_recent_rows_after_sorting(self):
        from datetime import date, timedelta
        rows = []
        start = date(2025, 1, 1)
        for offset in range(130):
            day = start + timedelta(days=offset)
            rows.append({
                "date": day.isoformat(), "open": 100, "high": 102,
                "low": 99, "close": 101, "volume": 1000,
            })
        result = EODHDClient("test-token", session=FakeSession(FakeResponse(payload=rows))).fetch_daily_prices_with_quality("SPY.US", "etf", limit=120)
        self.assertEqual(len(result["candles"]), 120)
        self.assertEqual(result["candles"][0]["date"], (start + timedelta(days=10)).isoformat())
        self.assertEqual(result["candles"][-1]["date"], (start + timedelta(days=129)).isoformat())

    def test_rejects_invalid_ohlc_and_duplicate_dates(self):
        rows = self.payload() + [
            {"date": "2026-11-12", "open": 680, "high": 670, "low": 678, "close": 684, "volume": 1}
        ]
        result = EODHDClient("test-token", session=FakeSession(FakeResponse(payload=rows))).fetch_daily_prices_with_quality("SPY.US", "etf")
        self.assertEqual(len(result["candles"]), 1)
        self.assertEqual(len(result["rejected_records"]), 1)

    def test_sanitizes_http_errors(self):
        for status, phrase in ((401, "HTTP 401"), (403, "HTTP 403"), (402, "HTTP 402"), (429, "HTTP 429")):
            client = EODHDClient("secret-token", session=FakeSession(FakeResponse(status_code=status, payload={})))
            with self.assertRaises(EODHDError) as caught:
                client.fetch_daily_prices_with_quality("SPY.US", "etf")
            self.assertIn(phrase, str(caught.exception))
            self.assertNotIn("secret-token", str(caught.exception))

    def test_rejects_unsupported_asset_and_ambiguous_symbol(self):
        client = EODHDClient("test-token", session=FakeSession(FakeResponse(payload=self.payload())))
        with self.assertRaises(ValueError):
            client.fetch_daily_prices_with_quality("SPY", "equity")
        with self.assertRaises(ValueError):
            client.fetch_daily_prices_with_quality("UNKNOWN", "etf")


if __name__ == "__main__":
    unittest.main()
