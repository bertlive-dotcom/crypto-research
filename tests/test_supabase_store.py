import unittest
from unittest.mock import patch, Mock
import requests

from supabase_store import SupabasePaperStore, SupabaseStoreError


class SupabaseStoreTests(unittest.TestCase):
    def test_requires_https_url_and_key(self):
        with self.assertRaises(ValueError):
            SupabasePaperStore("http://example.supabase.co", "key")
        with self.assertRaises(ValueError):
            SupabasePaperStore("https://example.supabase.co", "")

    @patch("supabase_store.requests.request")
    def test_load_state_returns_saved_json(self, request):
        response = Mock()
        response.content = b'[{"state":{"cash":80}}]'
        response.json.return_value = [{"state": {"cash": 80}}]
        request.return_value = response
        store = SupabasePaperStore("https://example.supabase.co", "secret")
        self.assertEqual(store.load_state(), {"cash": 80})

    @patch("supabase_store.requests.request")
    def test_save_state_calls_transactional_rpc(self, request):
        response = Mock()
        response.content = b""
        request.return_value = response
        store = SupabasePaperStore("https://example.supabase.co", "secret")
        event = {"event_type": "entry", "asset": "BTC"}
        store.save_state({"cash": 72}, event)
        self.assertIn("/rpc/save_paper_trading_state", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["json"], {"p_state": {"cash": 72}, "p_event": event})

    @patch("supabase_store.requests.request")
    def test_save_market_alerts_uses_deduplication_and_minimal_return(self, request):
        response = Mock()
        response.content = b'[{"dedupe_key":"BTC:confirmed_trend:2026-11-01","created_at":"2026-11-01T12:00:00+00:00"}]'
        response.json.return_value = [{"dedupe_key": "BTC:confirmed_trend:2026-11-01", "created_at": "2026-11-01T12:00:00+00:00"}]
        request.return_value = response
        store = SupabasePaperStore("https://example.supabase.co", "secret")
        alert = {"dedupe_key": "BTC:confirmed_trend:2026-11-01", "event_type": "confirmed_trend",
                 "asset": "BTC", "label": "Trend confirmed", "detail": "Daily and 4h aligned",
                 "daily_close": "2026-11-01T00:00:00+00:00", "four_hour_close": "2026-11-01T12:00:00+00:00",
                 "alert_class": "technical_confirmation"}

        inserted = store.save_market_alerts([alert])

        self.assertEqual(inserted[0]["dedupe_key"], alert["dedupe_key"])
        args, kwargs = request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/rest/v1/market_alert_events", args[1])
        self.assertEqual(kwargs["params"], {"on_conflict": "dedupe_key", "select": "dedupe_key,created_at"})
        self.assertEqual(kwargs["json"], [{key: value for key, value in alert.items() if key != "alert_class"}])
        self.assertEqual(kwargs["headers"]["Prefer"], "resolution=ignore-duplicates,return=representation")

    @patch("supabase_store.requests.request")
    def test_save_market_alerts_empty_list_does_not_request(self, request):
        store = SupabasePaperStore("https://example.supabase.co", "secret")
        self.assertEqual(store.save_market_alerts([]), [])
        request.assert_not_called()

    @patch("supabase_store.requests.request")
    def test_http_error_is_wrapped(self, request):
        response = Mock()
        response.content = b""
        response.raise_for_status.side_effect = requests.Timeout("timeout")
        request.return_value = response
        store = SupabasePaperStore("https://example.supabase.co", "secret")
        # A generic mocked exception should not be silently treated as success.
        with self.assertRaises(SupabaseStoreError):
            store.load_state()


if __name__ == "__main__":
    unittest.main()
