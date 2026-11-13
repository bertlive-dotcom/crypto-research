import unittest
from datetime import datetime, timezone, timedelta

from assistant.service import AssistantServiceError, ReadOnlyAssistantService


class FakeFeed:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {"source": "test", "data": [], "unavailable": []}
        self.error, self.calls = error, []

    def fetch(self, symbols=None, intervals=("1d", "4h"), limit=200):
        self.calls.append((symbols, intervals, limit))
        if self.error:
            raise self.error
        return self.payload


class FakeFinancialData:
    def __init__(self, candles=None, error=None):
        self.candles, self.error, self.calls = candles or [], error, []

    def fetch_daily_prices_with_quality(self, symbol, asset_class, limit=120):
        self.calls.append((symbol, asset_class, limit))
        if self.error:
            raise self.error
        return {"candles": self.candles, "rejected_records": []}


class FakeEODHD:
    def __init__(self, candles=None, error=None):
        self.candles, self.error, self.calls = candles or [], error, []

    def fetch_daily_prices_with_quality(self, symbol, asset_class, limit=120):
        self.calls.append((symbol, asset_class, limit))
        if self.error:
            raise self.error
        return {"candles": self.candles, "rejected_records": []}


class FakeAlphaVantage:
    def __init__(self, candles=None, error=None):
        self.candles, self.error, self.calls = candles or [], error, []

    def get_fx_daily(self, base, quote):
        self.calls.append((base, quote))
        if self.error:
            raise self.error
        return self.candles


def daily_candles(symbol, days=45, now=None, asset_class="equity", source="financialdata.net"):
    now = now or datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    start = now.date() - timedelta(days=days)
    rows = []
    for i in range(days):
        day = start + timedelta(days=i)
        close = 100 + i
        rows.append({
            "symbol": symbol, "asset_class": asset_class, "interval": "1d",
            "timestamp": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
            "close_timestamp": datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc).isoformat(),
            "open": close - 0.5, "high": close + 1, "low": close - 1,
            "close": close, "volume": 1000, "source": source,
        })
    return rows


class ReadOnlyAssistantServiceTests(unittest.TestCase):
    def test_returns_explicit_incomplete_crypto_report_when_no_history(self):
        feed = FakeFeed()
        report = ReadOnlyAssistantService(feed).crypto_overview(
            ["BTCUSD"], now=datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        )
        self.assertTrue(report["read_only"])
        self.assertEqual(report["mode"], "research_only")
        self.assertEqual(report["summary"]["with_both_timeframes"], 0)
        self.assertEqual(report["instruments"][0]["structure"]["category"], "insufficient_timeframes")
        self.assertEqual(feed.calls, [(["BTCUSD"], ("1d", "4h"), 200)])

    def test_rejects_unknown_and_duplicate_crypto_symbols_before_fetch(self):
        feed = FakeFeed()
        service = ReadOnlyAssistantService(feed)
        with self.assertRaises(ValueError):
            service.crypto_overview(["XAUUSD"])
        with self.assertRaises(ValueError):
            service.crypto_overview(["BTCUSD", "BTCUSD"])
        self.assertEqual(feed.calls, [])

    def test_rejects_unreasonable_crypto_history_limit(self):
        with self.assertRaises(ValueError):
            ReadOnlyAssistantService(FakeFeed()).crypto_overview(["BTCUSD"], limit=10)

    def test_crypto_feed_failure_is_sanitized(self):
        service = ReadOnlyAssistantService(FakeFeed(error=RuntimeError("secret detail")))
        with self.assertRaises(AssistantServiceError) as caught:
            service.crypto_overview(["BTCUSD"])
        self.assertNotIn("secret detail", str(caught.exception))

    def test_invalid_crypto_payload_fails_closed(self):
        service = ReadOnlyAssistantService(FakeFeed(payload={"unexpected": []}))
        with self.assertRaises(AssistantServiceError):
            service.crypto_overview(["BTCUSD"])

    def test_daily_equity_and_fx_analysis_does_not_claim_entitlement(self):
        now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        financial = FakeFinancialData(daily_candles("NVDA", now=now))
        alpha = FakeAlphaVantage(daily_candles("EURUSD", now=now, asset_class="forex", source="alpha_vantage"))
        service = ReadOnlyAssistantService(
            FakeFeed(), financialdata_client=financial, alphavantage_client=alpha
        )
        report = service.daily_multi_asset_overview(["NVDA", "EURUSD"], now=now)
        self.assertEqual(report["summary"]["returned"], 2)
        self.assertEqual(report["summary"]["data_quality_eligible"], 2)
        self.assertEqual(report["summary"]["entitlement_verified"], 0)
        self.assertTrue(all(not item["entitlement_verified"] for item in report["instruments"]))
        self.assertEqual(financial.calls[0][:2], ("NVDA", "equity"))
        self.assertEqual(alpha.calls, [("EUR", "USD")])

    def test_etf_uses_eodhd_personal_daily_provider(self):
        now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        financial = FakeFinancialData(error=RuntimeError("should not be called"))
        twelve = FakeTwelveData(daily_candles("SPY", now=now, asset_class="etf", source="eodhd"))
        report = ReadOnlyAssistantService(
            FakeFeed(), financialdata_client=financial, eodhd_client=twelve
        ).daily_multi_asset_overview(["SPY"], now=now)
        self.assertEqual(report["instruments"][0]["asset_class"], "etf")
        self.assertEqual(report["instruments"][0]["provider"], "eodhd")
        self.assertEqual(twelve.calls[0][:2], ("SPY.US", "etf"))
        self.assertEqual(financial.calls, [])

    def test_gold_spot_is_not_silently_enabled(self):
        with self.assertRaises(ValueError):
            ReadOnlyAssistantService(FakeFeed()).daily_multi_asset_overview(["XAUUSD"])

    def test_missing_provider_is_reported_without_failing_other_symbols(self):
        report = ReadOnlyAssistantService(FakeFeed()).daily_multi_asset_overview(["NVDA"])
        self.assertEqual(report["summary"]["returned"], 0)
        self.assertEqual(report["unavailable"][0]["reason"], "financialdata_adapter_not_configured")

    def test_etf_without_twelve_data_client_is_reported_unavailable(self):
        report = ReadOnlyAssistantService(FakeFeed()).daily_multi_asset_overview(["SPY"])
        self.assertEqual(report["summary"]["returned"], 0)
        self.assertEqual(report["unavailable"][0]["reason"], "eodhd_adapter_not_configured")

    def test_provider_errors_are_reported_without_leaking_details(self):
        service = ReadOnlyAssistantService(
            FakeFeed(), financialdata_client=FakeFinancialData(error=RuntimeError("private api key"))
        )
        report = service.daily_multi_asset_overview(["NVDA"])
        failure = report["unavailable"][0]
        self.assertEqual(failure["reason"], "financialdata_request_failed")
        self.assertEqual(failure["error_type"], "RuntimeError")
        self.assertEqual(failure["diagnostic"], "Provider error; details withheld for credential safety.")
        self.assertNotIn("private api key", str(report))

    def test_financialdata_adapter_error_exposes_safe_http_diagnostic(self):
        from global_markets.providers.financialdata import FinancialDataError

        service = ReadOnlyAssistantService(
            FakeFeed(), financialdata_client=FakeFinancialData(
                error=FinancialDataError("provider access denied (HTTP 403); check API-key validity and endpoint plan entitlement")
            )
        )
        report = service.daily_multi_asset_overview(["NVDA"])
        failure = report["unavailable"][0]
        self.assertEqual(failure["symbol"], "NVDA")
        self.assertEqual(failure["error_type"], "FinancialDataError")
        self.assertIn("HTTP 403", failure["diagnostic"])
        self.assertNotIn("api_key=", str(report))


if __name__ == "__main__":
    unittest.main()
