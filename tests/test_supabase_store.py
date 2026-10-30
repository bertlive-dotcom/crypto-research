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
