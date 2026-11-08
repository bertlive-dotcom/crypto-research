import unittest
from unittest.mock import Mock, patch

import requests

from global_markets.providers.bigdata import BigdataAPIError, BigdataClient


class BigdataClientTests(unittest.TestCase):
    def test_search_uses_official_endpoint_header_and_payload(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {"results": [{"title": "Example"}]}
        session.post.return_value = response

        client = BigdataClient("test-secret", session=session)
        result = client.search("Global markets today")

        self.assertEqual(result["results"][0]["title"], "Example")
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://api.bigdata.com/v1/search")
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "test-secret")
        self.assertEqual(kwargs["json"], {"query": {"text": "Global markets today"}})
        self.assertIn("timeout", kwargs)

    def test_missing_key_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            client = BigdataClient("")
        with self.assertRaisesRegex(BigdataAPIError, "BIGDATA_API_KEY"):
            client.search("test")

    def test_empty_query_rejected(self):
        client = BigdataClient("test-secret")
        with self.assertRaises(ValueError):
            client.search("  ")

    def test_rate_limit_is_reported(self):
        session = Mock()
        response = Mock()
        response.status_code = 429
        response.ok = False
        response.headers = {"Retry-After": "30"}
        session.post.return_value = response
        client = BigdataClient("test-secret", session=session)
        with self.assertRaisesRegex(BigdataAPIError, "Retry after 30"):
            client.search("test")

    def test_auth_error_is_reported_without_leaking_key(self):
        session = Mock()
        response = Mock()
        response.status_code = 401
        response.ok = False
        session.post.return_value = response
        client = BigdataClient("super-secret-key", session=session)
        with self.assertRaises(BigdataAPIError) as context:
            client.search("test")
        self.assertNotIn("super-secret-key", str(context.exception))

    def test_network_error_is_wrapped(self):
        session = Mock()
        session.post.side_effect = requests.Timeout()
        client = BigdataClient("test-secret", session=session)
        with self.assertRaisesRegex(BigdataAPIError, "Bigdata request failed: Timeout"):
            client.search("test")

    def test_non_json_response_is_rejected(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.ok = True
        response.json.side_effect = ValueError("invalid json")
        session.post.return_value = response
        client = BigdataClient("test-secret", session=session)
        with self.assertRaisesRegex(BigdataAPIError, "non-JSON"):
            client.search("test")

    def test_non_object_json_response_is_rejected(self):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = ["unexpected"]
        session.post.return_value = response
        client = BigdataClient("test-secret", session=session)
        with self.assertRaisesRegex(BigdataAPIError, "unexpected response format"):
            client.search("test")


if __name__ == "__main__":
    unittest.main()
