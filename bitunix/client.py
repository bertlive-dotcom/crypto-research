"""Read-only Bitunix account client.

Only fixed GET endpoints are implemented. This module intentionally exposes
no order, transfer, withdrawal, or account-mutation methods.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Mapping

import requests


SPOT_BASE_URL = "https://openapi.bitunix.com"
FUTURES_BASE_URL = "https://fapi.bitunix.com"
SPOT_BALANCE_PATH = "/api/spot/v1/user/account"
FUTURES_ACCOUNT_PATH = "/api/v1/futures/account"
FUTURES_POSITIONS_PATH = "/api/v1/futures/position/get_pending_positions"


class BitunixAPIError(RuntimeError):
    """Sanitized Bitunix API or transport error."""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_signature(
    *,
    nonce: str,
    timestamp: str,
    api_key: str,
    api_secret: str,
    params: Mapping[str, Any] | None = None,
    body: str = "",
) -> str:
    """Build Bitunix's documented double-SHA256 REST signature."""
    query_string = "".join(
        f"{key}{params[key]}" for key in sorted(params or {})
    )
    digest = _sha256_hex(nonce + timestamp + api_key + query_string + body)
    return _sha256_hex(digest + api_secret)


class BitunixReadOnlyClient:
    """Small allow-listed client for read-only Spot and Futures account data."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 12.0,
        clock=time.time,
        nonce_factory=None,
    ):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Bitunix API key is required")
        if not isinstance(api_secret, str) or not api_secret.strip():
            raise ValueError("Bitunix API secret is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.clock = clock
        self.nonce_factory = nonce_factory or (lambda: secrets.token_hex(8))

    def _get(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = dict(params or {})
        nonce = str(self.nonce_factory())
        timestamp = str(int(self.clock() * 1000))
        signature = build_signature(
            nonce=nonce,
            timestamp=timestamp,
            api_key=self.api_key,
            api_secret=self.api_secret,
            params=query,
        )
        headers = {
            "api-key": self.api_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": signature,
            "Content-Type": "application/json",
            "language": "en-US",
        }
        try:
            response = self.session.get(
                base_url + path,
                params=query or None,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {401, 403}:
                raise BitunixAPIError(
                    f"Bitunix rejected the read-only request (HTTP {status}); verify key permissions and API configuration"
                ) from exc
            if status == 429:
                raise BitunixAPIError("Bitunix rate limit reached; wait before retrying") from exc
            raise BitunixAPIError("Bitunix request failed; check network access and service availability") from exc
        except ValueError as exc:
            raise BitunixAPIError("Bitunix returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise BitunixAPIError("Bitunix returned an unexpected response format")
        code = payload.get("code")
        if code is not None and str(code) != "0":
            message = payload.get("msg") or payload.get("message") or "API request rejected"
            raise BitunixAPIError(f"Bitunix API error {code}: {message}")
        if payload.get("success") is False:
            message = payload.get("msg") or payload.get("message") or "API request rejected"
            raise BitunixAPIError(f"Bitunix API request failed: {message}")
        return payload

    def get_spot_balances(self) -> list[dict[str, Any]]:
        """Return Spot account balances using the documented read endpoint."""
        payload = self._get(SPOT_BASE_URL, SPOT_BALANCE_PATH)
        data = payload.get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise BitunixAPIError("Bitunix Spot balance response has an invalid data shape")
        return [row for row in data if isinstance(row, dict)]

    def get_futures_account(self, margin_coin: str = "USDT") -> list[dict[str, Any]]:
        """Return Futures account summary for one margin coin."""
        if margin_coin != "USDT":
            raise ValueError("Only USDT-margined Futures account reads are enabled")
        payload = self._get(
            FUTURES_BASE_URL,
            FUTURES_ACCOUNT_PATH,
            {"marginCoin": margin_coin},
        )
        data = payload.get("data")
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        if not isinstance(data, list):
            raise BitunixAPIError("Bitunix Futures account response has an invalid data shape")
        return [row for row in data if isinstance(row, dict)]

    def get_futures_positions(self) -> list[dict[str, Any]]:
        """Return currently open Futures positions; this is a GET-only endpoint."""
        payload = self._get(FUTURES_BASE_URL, FUTURES_POSITIONS_PATH)
        data = payload.get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise BitunixAPIError("Bitunix Futures positions response has an invalid data shape")
        return [row for row in data if isinstance(row, dict)]
