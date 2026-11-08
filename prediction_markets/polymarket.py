"""Read-only Polymarket public market-data adapter.

Discovery uses tagged event feeds because sorting all markets globally by
volume can return mostly unrelated categories. No wallet or execution APIs
are used.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

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

        tags = list(raw.get("tags") or [])
        event_context = " ".join(
            str(raw.get(key) or "") for key in ("event_title", "event_description")
        )
        tags.append(event_context)
        question = str(raw.get("question") or raw.get("title") or "Untitled market")
        slug = raw.get("event_slug") or raw.get("slug")
        token_ids = cls._as_list(raw.get("clobTokenIds"))
        yes_index = next(
            (index for index, outcome in enumerate(outcomes) if str(outcome).strip().lower() == "yes"),
            None,
        )
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
            "yes_token_id": token_ids[yes_index] if yes_index is not None and len(token_ids) > yes_index else None,
            "active": bool(raw.get("active", True)),
            "closed": bool(raw.get("closed", False)),
            "source": "Polymarket Gamma API",
        }

    def fetch_markets(self, limit: int = 100, categories=None) -> dict:
        """Fetch active crypto/macro event feeds and flatten their markets."""
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")

        allowed = set(categories or ("crypto", "macro"))
        invalid = allowed.difference({"crypto", "macro", "other"})
        if invalid:
            raise ValueError("Unsupported categories: " + ", ".join(sorted(invalid)))

        markets_by_id = {}
        event_counts = {}
        for tag_slug in ("crypto", "macro"):
            payload = self._get_json(
                f"{self.gamma_base_url}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "tag_slug": tag_slug,
                    "limit": limit,
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            if not isinstance(payload, list):
                raise PolymarketDataError(
                    f"Unexpected Gamma API response for {tag_slug}: expected a list"
                )
            event_counts[tag_slug] = len(payload)

            for event in payload:
                if not isinstance(event, dict):
                    continue
                nested_markets = event.get("markets")
                if not isinstance(nested_markets, list):
                    continue
                for raw in nested_markets:
                    if not isinstance(raw, dict):
                        continue
                    enriched = {
                        **raw,
                        "tags": list(raw.get("tags") or []) + list(event.get("tags") or []),
                        "event_title": event.get("title") or event.get("question"),
                        "event_description": event.get("description"),
                        "event_slug": event.get("slug"),
                        "volume24hr": raw.get("volume24hr", event.get("volume24hr")),
                        "liquidityNum": raw.get("liquidityNum", event.get("liquidity")),
                    }
                    normalized = self.normalize_market(enriched)
                    if normalized["active"] and not normalized["closed"]:
                        if normalized["category"] in allowed and normalized["market_id"]:
                            markets_by_id[normalized["market_id"]] = normalized

        markets = sorted(
            markets_by_id.values(),
            key=lambda row: row.get("volume_usd") or 0,
            reverse=True,
        )
        return {
            "source": "Polymarket Gamma API (tagged events)",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "requested_per_category": limit,
            "event_counts": event_counts,
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
