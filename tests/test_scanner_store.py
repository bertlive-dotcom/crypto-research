import unittest
from unittest.mock import MagicMock, patch

from scanner.store import ScannerStore


class LatestCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.store = ScannerStore("https://example.supabase.co", "test-service-key")

    @staticmethod
    def response(rows):
        response = MagicMock()
        response.content = b"[]" if rows is not None else b""
        response.json.return_value = rows
        response.raise_for_status.return_value = None
        return response

    @patch("scanner.store.requests.request")
    def test_latest_candidates_reads_only_newest_scan_and_deduplicates_symbols(self, request):
        scan_time = "2026-11-01T14:30:00+00:00"
        request.side_effect = [
            self.response([{"scanned_at": scan_time}]),
            self.response([
                {"symbol": "UNIUSDT", "score": 85, "scanned_at": scan_time},
                {"symbol": "CELOUSDT", "score": 85, "scanned_at": scan_time},
                {"symbol": "UNIUSDT", "score": 80, "scanned_at": scan_time},
            ]),
        ]

        rows = self.store.latest_candidates(limit=50)

        self.assertEqual([row["symbol"] for row in rows], ["UNIUSDT", "CELOUSDT"])
        self.assertEqual(request.call_count, 2)
        first_params = request.call_args_list[0].kwargs["params"]
        second_params = request.call_args_list[1].kwargs["params"]
        self.assertEqual(first_params["order"], "scanned_at.desc")
        self.assertEqual(second_params["scanned_at"], "eq." + scan_time)

    @patch("scanner.store.requests.request")
    def test_latest_candidates_returns_empty_when_no_recent_scan_exists(self, request):
        request.return_value = self.response([])
        self.assertEqual(self.store.latest_candidates(), [])
        self.assertEqual(request.call_count, 1)

    @patch("scanner.store.requests.request")
    def test_latest_candidates_clamps_limit(self, request):
        request.side_effect = [
            self.response([{"scanned_at": "2026-11-01T14:30:00+00:00"}]),
            self.response([]),
        ]
        self.store.latest_candidates(limit=5000)
        self.assertEqual(request.call_args_list[1].kwargs["params"]["limit"], "500")


if __name__ == "__main__":
    unittest.main()
