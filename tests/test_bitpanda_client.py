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
        self.assertEqual(
            session.get.call_args.args[0],
            "https://api.public.bitpanda.com/v1/portfolio/holdings",
        )

    def test_history_validates_timeframe(self):
        client, _ = self.client({"data": []})
        with self.assertRaises(ValueError):
            client.get_history("INVALID")

    def test_operations_uses_rest_page_size_and_camel_case_cursor(self):
        client, session = self.client({"data": [], "nextCursor": "next"})
        session.get.side_effect = [
            FakeResponse({"data": [{"operationId": "a"}], "nextCursor": "next"}),
            FakeResponse({"data": [{"operationId": "b"}], "hasNextPage": False}),
        ]
        self.assertEqual(
            [x["operationId"] for x in client.get_operations()],
            ["a", "b"],
        )
        self.assertEqual(session.get.call_args_list[0].kwargs["params"], {"page_size": 100})
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"],
            {"page_size": 100, "cursor": "next"},
        )

    def test_earn_uses_rest_page_size(self):
        client, session = self.client({"data": []})
        client.get_earn_configs()
        self.assertEqual(session.get.call_args.kwargs["params"], {"page_size": 250})

    def test_missing_key_rejected(self):
        with self.assertRaises(ValueError):
            BitpandaClient("")

    def test_forbidden_scope_has_clear_error(self):
        client, _ = self.client({"error": "forbidden"}, status=403)
        with self.assertRaises(BitpandaAPIError):
            client.get_holdings()


if __name__ == "__main__":
    unittest.main()
