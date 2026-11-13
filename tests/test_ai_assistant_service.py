import unittest
from datetime import datetime, timezone

from assistant.service import AssistantServiceError, ReadOnlyAssistantService


class FakeFeed:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {"source": "test", "data": [], "unavailable": []}
        self.error = error
        self.calls = []

    def fetch(self, symbols=None, intervals=("1d", "4h"), limit=200):
        self.calls.append((symbols, intervals, limit))
        if self.error:
            raise self.error
        return self.payload


class ReadOnlyAssistantServiceTests(unittest.TestCase):
    def test_returns_explicit_incomplete_report_when_no_history(self):
        feed = FakeFeed()
        service = ReadOnlyAssistantService(feed)
        now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        report = service.crypto_overview(["BTCUSD"], now=now)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["mode"], "research_only")
        self.assertEqual(report["summary"]["with_both_timeframes"], 0)
        self.assertEqual(report["instruments"][0]["structure"]["category"], "insufficient_timeframes")
        self.assertEqual(feed.calls, [(["BTCUSD"], ("1d", "4h"), 200)])

    def test_rejects_unknown_and_duplicate_symbols_before_fetch(self):
        feed = FakeFeed()
        service = ReadOnlyAssistantService(feed)
        with self.assertRaises(ValueError):
            service.crypto_overview(["XAUUSD"])
        with self.assertRaises(ValueError):
            service.crypto_overview(["BTCUSD", "BTCUSD"])
        self.assertEqual(feed.calls, [])

    def test_rejects_unreasonable_history_limit(self):
        service = ReadOnlyAssistantService(FakeFeed())
        with self.assertRaises(ValueError):
            service.crypto_overview(["BTCUSD"], limit=10)

    def test_feed_failure_is_sanitized(self):
        service = ReadOnlyAssistantService(FakeFeed(error=RuntimeError("secret detail")))
        with self.assertRaises(AssistantServiceError) as caught:
            service.crypto_overview(["BTCUSD"])
        self.assertNotIn("secret detail", str(caught.exception))

    def test_invalid_feed_payload_fails_closed(self):
        service = ReadOnlyAssistantService(FakeFeed(payload={"unexpected": []}))
        with self.assertRaises(AssistantServiceError):
            service.crypto_overview(["BTCUSD"])


if __name__ == "__main__":
    unittest.main()
