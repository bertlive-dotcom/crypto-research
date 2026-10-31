"""Supabase persistence isolated from the existing dashboard paper ledger."""
from __future__ import annotations
import requests
from .config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

class ScannerStoreError(RuntimeError):
    pass

class ScannerStore:
    def __init__(self, url: str = SUPABASE_URL, key: str = SUPABASE_SERVICE_ROLE_KEY, timeout: int = 15):
        if not url.startswith("https://") or not key:
            raise ValueError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY for the scanner service.")
        self.url, self.key, self.timeout = url.rstrip("/"), key, timeout
        self.headers = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = requests.request(method, self.url + "/rest/v1/" + path,
                headers=self.headers, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        except requests.RequestException as exc:
            detail = getattr(getattr(exc, "response", None), "text", "")[:300]
            raise ScannerStoreError(detail or str(exc)) from exc

    def rpc(self, name: str, payload: dict):
        return self._request("POST", "rpc/" + name, json=payload)

    def acquire_lock(self, worker_id: str, lease_seconds: int = 240) -> bool:
        result = self.rpc("acquire_market_scanner_lock", {"p_worker_id": worker_id, "p_lease_seconds": lease_seconds})
        return bool(result)

    def release_lock(self, worker_id: str) -> None:
        self.rpc("release_market_scanner_lock", {"p_worker_id": worker_id})

    def load_state(self) -> dict | None:
        rows = self._request("GET", "scanner_paper_state", params={"id": "eq.default", "select": "state", "limit": "1"})
        return rows[0]["state"] if rows else None

    def save_cycle(self, state: dict, run: dict, candidates: list[dict], signals: list[dict]) -> None:
        self.rpc("save_market_scanner_cycle", {
            "p_state": state, "p_run": run, "p_candidates": candidates, "p_signals": signals
        })

    def latest_candidates(self, limit: int = 50) -> list[dict]:
        return self._request("GET", "market_candidates", params={
            "select": "symbol,score,eligible,auto_entry_eligible,price_usdt,quote_volume_24h,change_24h_pct,scanned_at,features,reasons",
            "order": "score.desc", "limit": str(limit)
        }) or []
