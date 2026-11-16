import unittest
from unittest.mock import Mock

from bitpanda.client import BitpandaClient, BitpandaAPIError


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            error = requests.HTTPError("HTTP {}".format(self.status_code))
            error.response = self
            raise error

    def json(self):
        return self.payload


class BitpandaClientTests(unittest.TestCase):
    def client(self, payload, status=200):
        session = Mock()
        session.headers = {}
        session.get.return_value = FakeResponse(payload, status)
        return BitpandaClient("test-key", session=session), session

    def test_holdings_extracts_data_list(self):
        client, session = self.client({"data": [{"symbol": "BTC"}]})
        self.assertEqual(client.get_holdings(), [{"symbol": "BTC"}])
        self.assertEqual(session.get.call_args.args[0], "https://api.public.bitpanda.com/v1/portfolio/holdings")

    def test_history_validates_timeframe(self):
        client, _ = self.client({"data": {"datapoints": [{"time": "2026-01-01"}]}})
        with self.assertRaises(ValueError):
            client.get_history("INVALID")

    def test_operations_follows_cursor(self):
        client, session = self.client({"data": [{"id": "a"}], "nextCursor": "next"})
        session.get.side_effect = [
            FakeResponse({"data": [{"id": "a"}], "nextCursor": "next"}),
            FakeResponse({"data": [{"id": "b"}]}),
        ]
        self.assertEqual([x["id"] for x in client.get_operations()], ["a", "b"])

    def test_missing_key_rejected(self):
        with self.assertRaises(ValueError):
            BitpandaClient("")

    def test_forbidden_scope_has_clear_error(self):
        client, _ = self.client({"error": "forbidden"}, status=403)
        with self.assertRaises(BitpandaAPIError):
            client.get_holdings()


if __name__ == "__main__":
    unittest.main()
