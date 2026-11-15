import unittest
from datetime import datetime, timedelta, timezone

from equity_engine import AnalysisRequest, EquityAnalysisService, Instrument
from global_markets.providers.financialdata import FinancialDataError


NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


class FakeProvider:
    def __init__(self):
        self.calls = []

    def fetch_daily_prices_with_quality(
        self, symbol, asset_class, *, international, limit
    ):
        self.calls.append((symbol, asset_class, international, limit))
        if symbol == "FAIL":
            raise FinancialDataError("secret=should-not-be-returned")
        candles = []
        for index in range(80):
            close_at = NOW - timedelta(days=80 - index)
            close = 100 + index
            candles.append({
                "symbol": symbol,
                "interval": "1d",
                "source": "fixture",
                "timestamp": (close_at - timedelta(hours=23, minutes=59)).isoformat(),
                "close_timestamp": close_at.isoformat(),
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            })
        return {
            "candles": candles,
            "source_records": len(candles),
            "rejected_records": [],
        }


class EquityAnalysisServiceTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.service = EquityAnalysisService(self.provider, "fixture-provider")

    def request(self, instruments=None, **kwargs):
        return AnalysisRequest(
            instruments=tuple(instruments or [Instrument("NVDA", "Nvidia")]),
            requested_at=NOW,
            **kwargs,
        )

    def test_returns_versioned_technical_analysis(self):
        result = self.service.analyze(self.request(), now=NOW)
        payload = result.to_dict()
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(payload["source"], "fixture-provider")
        self.assertEqual(len(payload["analyses"]), 1)
        self.assertTrue(payload["analyses"][0]["eligible"])
        self.assertEqual(
            payload["analyses"][0]["score_type"],
            "technical_only_not_investment_recommendation",
        )

    def test_provider_failure_isolated_and_secret_text_not_exposed(self):
        result = self.service.analyze(
            self.request([Instrument("FAIL", "Failure"), Instrument("MSFT", "Microsoft")]),
            now=NOW,
        )
        self.assertEqual(len(result.unavailable), 1)
        self.assertEqual(result.unavailable[0]["symbol"], "FAIL")
        self.assertNotIn("secret", str(result.to_dict()))
        self.assertEqual(len(result.analyses), 1)
        self.assertTrue(result.analyses[0]["eligible"])

    def test_provider_receives_asset_class_exchange_flag_and_limit(self):
        request = self.request(
            [Instrument("SU.PA", "Schneider Electric", international=True)],
            history_limit=90,
        )
        self.service.analyze(request, now=NOW)
        self.assertEqual(
            self.provider.calls[0],
            ("SU.PA", "equity", True, 90),
        )

    def test_rejected_provider_rows_are_reported_separately(self):
        class ProviderWithRejectedRows(FakeProvider):
            def fetch_daily_prices_with_quality(self, *args, **kwargs):
                feed = super().fetch_daily_prices_with_quality(*args, **kwargs)
                feed["rejected_records"] = [
                    {"date": "2026-11-01", "reason": "duplicate observation"}
                ]
                return feed

        service = EquityAnalysisService(ProviderWithRejectedRows(), "fixture")
        result = service.analyze(self.request(), now=NOW)
        self.assertEqual(result.quality[0]["rejected_records"], 1)
        self.assertEqual(
            result.quality[0]["examples"][0]["reason"],
            "duplicate observation",
        )

    def test_request_rejects_duplicate_symbols_and_invalid_history(self):
        with self.assertRaises(ValueError):
            self.request([Instrument("NVDA", "Nvidia"), Instrument("nvda", "Duplicate")])
        with self.assertRaises(ValueError):
            self.request(history_limit=500)

    def test_instrument_only_accepts_equity_or_etf(self):
        with self.assertRaises(ValueError):
            Instrument("BTCUSD", "Bitcoin", asset_class="crypto")


if __name__ == "__main__":
    unittest.main()
