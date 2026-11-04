import unittest
from datetime import datetime, timedelta, timezone

from global_markets.equity_research import EQUITY_UNIVERSE, analyse_equity_universe
from global_markets.providers.financialdata import FinancialDataError


class FakeClient:
    def __init__(self):
        self.calls = []

    def fetch_daily_prices_with_quality(self, symbol, asset_class, *, international, limit):
        self.calls.append((symbol, asset_class, international, limit))
        if symbol == "TSM":
            raise FinancialDataError("provider failure")
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        candles = []
        for index in range(80):
            day = now - timedelta(days=80 - index)
            close = 100 + index
            candles.append({
                "symbol": symbol,
                "interval": "1d",
                "timestamp": day.replace(hour=0, minute=0, second=0).isoformat(),
                "close_timestamp": day.replace(hour=23, minute=59, second=59).isoformat(),
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
                "source": "fake",
            })
        return {"candles": candles, "source_records": 80, "rejected_records": []}


class EquityResearchTests(unittest.TestCase):
    def test_universe_contains_expected_eight_companies(self):
        self.assertEqual(
            [item["symbol"] for item in EQUITY_UNIVERSE],
            ["NVDA", "TSM", "ASML", "MSFT", "GOOGL", "AMZN", "AVGO", "SU.PA"],
        )

    def test_schneider_uses_international_endpoint(self):
        client = FakeClient()
        analyse_equity_universe(client, now=datetime(2026, 11, 4, tzinfo=timezone.utc))
        schneider = [call for call in client.calls if call[0] == "SU.PA"]
        self.assertEqual(len(schneider), 1)
        self.assertTrue(schneider[0][2])

    def test_one_provider_failure_does_not_abort_other_symbols(self):
        client = FakeClient()
        result = analyse_equity_universe(client, now=datetime(2026, 11, 4, tzinfo=timezone.utc))
        self.assertEqual(result["universe_size"], 8)
        self.assertEqual(len(result["unavailable"]), 1)
        self.assertEqual(result["unavailable"][0]["symbol"], "TSM")
        self.assertEqual(len(result["analyses"]), 7)
        self.assertEqual(result["valid_count"], 7)

    def test_limit_is_passed_to_provider(self):
        client = FakeClient()
        analyse_equity_universe(client, limit=90, now=datetime(2026, 11, 4, tzinfo=timezone.utc))
        self.assertTrue(all(call[3] == 90 for call in client.calls))


if __name__ == "__main__":
    unittest.main()
