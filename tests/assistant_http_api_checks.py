import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from assistant import http_api


class AssistantReadOnlyHttpApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(http_api.app)
        self.token = "test-internal-service-token"

    def test_requires_service_token(self):
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": self.token}):
            response = self.client.get(
                "/internal/v1/assistant/crypto-overview",
                params={"symbols": "BTCUSD"},
            )
        self.assertEqual(response.status_code, 401)

    def test_fails_closed_when_token_is_not_configured(self):
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": ""}):
            response = self.client.get(
                "/internal/v1/assistant/crypto-overview",
                params={"symbols": "BTCUSD"},
                headers={"Authorization": f"Bearer {self.token}"},
            )
        self.assertEqual(response.status_code, 503)

    def test_returns_read_only_service_payload(self):
        payload = {
            "schema_version": "1.1",
            "generated_at": "2026-11-22T10:00:00+00:00",
            "source": "binance",
            "read_only": True,
            "mode": "research_only",
            "instruments": [],
            "unavailable": [],
        }
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": self.token}):
            with patch.object(http_api.service, "crypto_overview", return_value=payload) as mocked:
                response = self.client.get(
                    "/internal/v1/assistant/crypto-overview",
                    params={"symbols": "BTCUSD,ETHUSD", "limit": 120},
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        mocked.assert_called_once_with(["BTCUSD", "ETHUSD"], limit=120)

    def test_rejects_duplicate_symbols_before_calling_service(self):
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": self.token}):
            with patch.object(http_api.service, "crypto_overview") as mocked:
                response = self.client.get(
                    "/internal/v1/assistant/crypto-overview",
                    params={"symbols": "BTCUSD,BTCUSD"},
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        self.assertEqual(response.status_code, 422)
        mocked.assert_not_called()

    def test_strategy_validation_endpoint_requires_auth_and_returns_simulation_data(self):
        payload = {
            "schema_version": "1.0", "read_only": True, "mode": "simulation_only",
            "quote_currency": "USDT", "trade_count": 0, "cost_incomplete_count": 0,
            "trades": [], "candidates": [], "limitations": [],
        }
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": self.token}):
            with patch.object(http_api.strategy_validation_service, "dataset", return_value=payload) as mocked:
                response = self.client.get(
                    "/internal/v1/strategy-validation/dataset",
                    params={"symbol": "BTCUSDT", "limit": 100},
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        mocked.assert_called_once_with(symbol="BTCUSDT", limit=100)

    def test_strategy_validation_endpoint_rejects_invalid_request(self):
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": self.token}):
            response = self.client.get(
                "/internal/v1/strategy-validation/dataset",
                params={"limit": 0},
                headers={"Authorization": f"Bearer {self.token}"},
            )
        self.assertEqual(response.status_code, 422)

    def test_rejects_invalid_symbol_as_client_error(self):
        with patch.dict(os.environ, {"CRYPTO_RESEARCH_INTERNAL_API_TOKEN": self.token}):
            with patch.object(http_api.service, "crypto_overview", side_effect=ValueError("unsupported")):
                response = self.client.get(
                    "/internal/v1/assistant/crypto-overview",
                    params={"symbols": "XAUUSD"},
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
