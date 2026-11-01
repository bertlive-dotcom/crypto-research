"""Supabase-backed persistence for paper trading and technical alert history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

import requests


class SupabaseStoreError(RuntimeError):
    """Raised when the Supabase ledger cannot be read or written."""


class SupabasePaperStore:
    def __init__(self, url: str, service_role_key: str, timeout: int = 10):
        self.url = (url or "").strip().rstrip("/")
        self.key = (service_role_key or "").strip()
        self.timeout = timeout
        if not self.url.startswith("https://") or not self.key:
            raise ValueError("A valid HTTPS SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        self.headers = {
            "apikey": self.key,
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs):
        extra_headers = kwargs.pop("headers", None) or {}
        headers = {**self.headers, **extra_headers}
        try:
            response = requests.request(
                method, self.url + "/rest/v1/" + path,
                headers=headers, timeout=self.timeout, **kwargs
            )
            response.raise_for_status()
            return response.json() if response.content else None
        except requests.RequestException as exc:
            detail = getattr(getattr(exc, "response", None), "text", "")[:300]
            raise SupabaseStoreError("Supabase request failed: " + (detail or str(exc))) from exc

    def load_state(self) -> Optional[dict]:
        rows = self._request(
            "GET", "paper_trading_state",
            params={"id": "eq.default", "select": "state", "limit": "1"},
        )
        return rows[0]["state"] if rows else None

    def save_state(self, state: dict, event: Optional[dict] = None) -> None:
        self._request(
            "POST", "rpc/save_paper_trading_state",
            json={"p_state": state, "p_event": event},
        )

    def load_events(self, days: int = 30, limit: int = 5000) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self._request(
            "GET", "paper_trading_events",
            params={
                "select": "id,event_type,asset,payload,created_at",
                "created_at": "gte." + since,
                "order": "created_at.desc",
                "limit": str(limit),
            },
        ) or []

    def load_market_alerts(self, days: int = 90, limit: int = 500) -> list[dict]:
        """Load durable technical alerts from the separate market_alert_events table."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self._request(
            "GET", "market_alert_events",
            params={
                "select": "dedupe_key,event_type,asset,label,detail,daily_close,four_hour_close,created_at",
                "created_at": "gte." + since,
                "order": "created_at.desc",
                "limit": str(limit),
            },
        ) or []

    def save_market_alerts(self, alerts: list[dict]) -> None:
        """Insert new alerts; duplicate dedupe keys are ignored by the database."""
        if not alerts:
            return
        # alert_class is presentation metadata introduced in the app; keep the
        # durable row compatible with existing tables that predate that field.
        columns = ("dedupe_key", "event_type", "asset", "label", "detail",
                   "daily_close", "four_hour_close")
        rows = [{key: alert.get(key) for key in columns} for alert in alerts]
        self._request(
            "POST", "market_alert_events",
            params={"on_conflict": "dedupe_key"},
            headers={**self.headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
            json=rows,
        )
