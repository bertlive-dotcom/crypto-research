import unittest

from bitunix.client import (
    BitunixAPIError,
    BitunixReadOnlyClient,
    FUTURES_ACCOUNT_PATH,
    FUTURES_BASE_URL,
    FUTURES_POSITIONS_PATH,
    SPOT_BALANCE_PATH,
    SPOT_BASE_URL,
    build_signature,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError("HTTP error", response=response)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({
            "url": url, "params": params, "headers": headers, "timeout": timeout
        })
        return self.payloads.pop(0)


class BitunixReadOnlyTests(unittest.TestCase):
    def test_double_sha256_signature_uses_sorted_query_keys(self):
        first = build_signature(
            nonce="n1", timestamp="1700000000000", api_key="key",
            api_secret="secret", params={"z": "9", "a": "1"},
        )
        second = build_signature(
            nonce="n1", timestamp="1700000000000", api_key="key",
            api_secret="secret", params={"a": "1", "z": "9"},
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_spot_balance_uses_fixed_get_endpoint_and_signed_headers(self):
        session = FakeSession([FakeResponse({
            "code": 0, "data": [{"coin": "USDT", "balance": "12.5", "balanceLocked": "0"}]
        })])
        client = BitunixReadOnlyClient(
            "test-key", "test-secret", session=session,
            clock=lambda: 1700000000, nonce_factory=lambda: "fixed-nonce",
        )
        rows = client.get_spot_balances()
        self.assertEqual(rows[0]["coin"], "USDT")
        call = session.calls[0]
        self.assertEqual(call["url"], SPOT_BASE_URL + SPOT_BALANCE_PATH)
        self.assertEqual(call["headers"]["api-key"], "test-key")
        self.assertEqual(call["headers"]["nonce"], "fixed-nonce")
        self.assertEqual(call["headers"]["timestamp"], "1700000000000")
        self.assertTrue(call["headers"]["sign"])

    def test_futures_account_sends_usdt_margin_coin(self):
        session = FakeSession([FakeResponse({
            "code": 0, "data": [{"marginCoin": "USDT", "available": "100"}]
        })])
        client = BitunixReadOnlyClient("key", "secret", session=session)
        rows = client.get_futures_account()
        self.assertEqual(rows[0]["marginCoin"], "USDT")
        self.assertEqual(session.calls[0]["url"], FUTURES_BASE_URL + FUTURES_ACCOUNT_PATH)
        self.assertEqual(session.calls[0]["params"], {"marginCoin": "USDT"})

    def test_futures_positions_uses_fixed_get_endpoint(self):
        session = FakeSession([FakeResponse({
            "code": 0, "data": [{"symbol": "BTCUSDT", "positionId": "position-1"}]
        })])
        client = BitunixReadOnlyClient("key", "secret", session=session)

        rows = client.get_futures_positions()

        self.assertEqual(rows, [{"symbol": "BTCUSDT", "positionId": "position-1"}])
        self.assertEqual(
            session.calls[0]["url"],
            FUTURES_BASE_URL + FUTURES_POSITIONS_PATH,
        )
        self.assertEqual(session.calls[0]["params"], None)

    def test_api_error_is_reported_without_exposing_credentials(self):
        session = FakeSession([FakeResponse({"code": 10001, "msg": "permission denied"})])
        client = BitunixReadOnlyClient("sensitive-key", "sensitive-secret", session=session)
        with self.assertRaises(BitunixAPIError) as caught:
            client.get_spot_balances()
        self.assertNotIn("sensitive-key", str(caught.exception))
        self.assertNotIn("sensitive-secret", str(caught.exception))

    def test_only_usdt_futures_account_is_enabled(self):
        client = BitunixReadOnlyClient("key", "secret", session=FakeSession([]))
        with self.assertRaises(ValueError):
            client.get_futures_account("BTC")

    def test_no_write_or_withdraw_methods_are_exposed(self):
        client = BitunixReadOnlyClient("key", "secret", session=FakeSession([]))
        self.assertFalse(hasattr(client, "place_order"))
        self.assertFalse(hasattr(client, "withdraw"))
        self.assertFalse(hasattr(client, "transfer"))


if __name__ == "__main__":
    unittest.main()
