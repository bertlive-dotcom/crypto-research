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

    def save_pmi_snapshots(self, markets: list[dict], observed_at: Optional[str] = None) -> int:
        """Upsert one 15-minute observation bucket for normalized PMI markets."""
        if not markets:
            return 0
        observed = observed_at or datetime.now(timezone.utc).isoformat()
        parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        bucket = parsed.replace(
            minute=(parsed.minute // 15) * 15, second=0, microsecond=0
        ).isoformat()
        columns = (
            "market_id", "question", "category", "yes_probability",
            "no_probability", "volume_usd", "liquidity_usd", "end_date",
            "source_updated_at", "market_url", "yes_token_id", "source",
        )
        rows = []
        for market in markets:
            if not market.get("market_id") or not market.get("question"):
                continue
            row = {key: market.get(key) for key in columns}
            row["market_url"] = market.get("url") or market.get("market_url")
            row["observed_at"] = parsed.isoformat()
            row["snapshot_bucket"] = bucket
            row["raw_data"] = market.get("raw_data") or {}
            rows.append(row)
        if not rows:
            return 0
        self._request(
            "POST", "pmi_market_snapshots",
            params={"on_conflict": "market_id,snapshot_bucket"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows,
        )
        return len(rows)

    def load_pmi_snapshots(self, days: int = 2, limit: int = 1000) -> list[dict]:
        """Load recent persisted PMI observations for the dashboard overview."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self._request(
            "GET", "pmi_market_snapshots",
            params={
                "select": "market_id,question,category,yes_probability,no_probability,volume_usd,liquidity_usd,end_date,source_updated_at,market_url,source,observed_at,snapshot_bucket",
                "observed_at": "gte." + since,
                "order": "observed_at.desc",
                "limit": str(limit),
            },
        ) or []

    def load_pmi_market_history(
        self, market_id: str, days: int = 7, limit: int = 1000
    ) -> list[dict]:
        """Load chronological probability history for one prediction market."""
        if not market_id:
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self._request(
            "GET", "pmi_market_snapshots",
            params={
                "select": "market_id,question,category,yes_probability,no_probability,volume_usd,liquidity_usd,observed_at,snapshot_bucket",
                "market_id": "eq." + market_id,
                "observed_at": "gte." + since,
                "order": "observed_at.asc",
                "limit": str(limit),
            },
        ) or []

    def save_market_alerts(self, alerts: list[dict]) -> list[dict]:
        """Insert new alerts and return only rows actually inserted by PostgREST."""
        if not alerts:
            return []
        # alert_class is presentation metadata introduced in the app; keep the
        # durable row compatible with existing tables that predate that field.
        columns = ("dedupe_key", "event_type", "asset", "label", "detail",
                   "daily_close", "four_hour_close")
        rows = [{key: alert.get(key) for key in columns} for alert in alerts]
        inserted = self._request(
            "POST", "market_alert_events",
            params={"on_conflict": "dedupe_key", "select": "dedupe_key,created_at"},
            headers={**self.headers, "Prefer": "resolution=ignore-duplicates,return=representation"},
            json=rows,
        )
        return inserted or []
