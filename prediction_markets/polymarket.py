"""Read-only Polymarket public market-data adapter.

Only public discovery and price-history endpoints are used. This module has
no wallet, authentication, order-placement, signing, or execution methods.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from .scoring import classify_market_category


class PolymarketDataError(RuntimeError):
    """Raised when public Polymarket data cannot be retrieved or validated."""


class PolymarketClient:
    GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_BASE_URL = "https://clob.polymarket.com"

    def __init__(
        self,
        session=None,
        timeout: int = 15,
        gamma_base_url: Optional[str] = None,
        clob_base_url: Optional[str] = None,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.gamma_base_url = (gamma_base_url or self.GAMMA_BASE_URL).rstrip("/")
        self.clob_base_url = (clob_base_url or self.CLOB_BASE_URL).rstrip("/")

    def _get_json(self, url: str, params=None):
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise PolymarketDataError(f"Public data request failed: {error}") from error
        return payload

    @staticmethod
    def _as_list(value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                return []
        return []

    @staticmethod
    def _number(value):
        try:
            number = float(value)
            return number if number >= 0 else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def normalize_market(cls, raw: dict) -> dict:
        outcomes = cls._as_list(raw.get("outcomes"))
        prices = cls._as_list(raw.get("outcomePrices"))
        yes_probability = None
        no_probability = None

        if len(outcomes) == len(prices):
            for outcome, price in zip(outcomes, prices):
                parsed_price = cls._number(price)
                label = str(outcome).strip().lower()
                if label == "yes":
                    yes_probability = parsed_price
                elif label == "no":
                    no_probability = parsed_price

        tags = raw.get("tags") or []
        question = str(raw.get("question") or raw.get("title") or "Untitled market")
        slug = raw.get("slug")
        token_ids = cls._as_list(raw.get("clobTokenIds"))
        return {
            "market_id": str(raw.get("id") or raw.get("conditionId") or ""),
            "question": question,
            "category": classify_market_category(question, tags),
            "yes_probability": yes_probability,
            "no_probability": no_probability,
            "volume_usd": cls._number(raw.get("volume24hr"))
                if raw.get("volume24hr") is not None
                else cls._number(raw.get("volumeNum", raw.get("volume"))),
            "liquidity_usd": cls._number(raw.get("liquidityNum", raw.get("liquidity"))),
            "end_date": raw.get("endDate"),
            "updated_at": raw.get("updatedAt") or raw.get("updated_at"),
            "url": f"https://polymarket.com/event/{slug}" if slug else None,
            "yes_token_id": token_ids[outcomes.index("Yes")] if (
                isinstance(outcomes, list) and "Yes" in outcomes and len(token_ids) > outcomes.index("Yes")
            ) else None,
            "active": bool(raw.get("active", True)),
            "closed": bool(raw.get("closed", False)),
            "source": "Polymarket Gamma API",
        }

    def fetch_markets(self, limit: int = 100, categories=None) -> dict:
        """Fetch active, unresolved markets and return normalized observations."""
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer between 1 and 500")

        payload = self._get_json(
            f"{self.gamma_base_url}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": limit,
                "order": "volumeNum",
                "ascending": "false",
            },
        )
        if not isinstance(payload, list):
            raise PolymarketDataError("Unexpected Gamma API response: expected a list")

        allowed = set(categories or ("crypto", "macro"))
        markets = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            normalized = self.normalize_market(raw)
            if normalized["active"] and not normalized["closed"]:
                if normalized["category"] in allowed:
                    markets.append(normalized)

        return {
            "source": "Polymarket Gamma API",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "requested": limit,
            "returned": len(markets),
            "markets": markets,
        }

    def fetch_price_history(self, token_id: str, interval: str = "1d", fidelity: int = 60) -> list:
        """Fetch public CLOB history for an outcome token; read-only endpoint."""
        if not token_id or not isinstance(token_id, str):
            raise ValueError("token_id is required")
        payload = self._get_json(
            f"{self.clob_base_url}/prices-history",
            params={"market": token_id, "interval": interval, "fidelity": fidelity},
        )
        history = payload.get("history") if isinstance(payload, dict) else None
        if not isinstance(history, list):
            raise PolymarketDataError("Unexpected CLOB history response")
        points = []
        for item in history:
            if not isinstance(item, dict):
                continue
            try:
                timestamp = int(item["t"])
                probability = float(item["p"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= probability <= 1:
                points.append({"timestamp": timestamp, "probability": probability})
        return points
