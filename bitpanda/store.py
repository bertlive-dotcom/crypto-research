"""Persistence for read-only Bitpanda snapshots in Supabase."""
from __future__ import annotations

from datetime import datetime, timezone
import requests


class BitpandaStoreError(RuntimeError):
    pass


class BitpandaPortfolioStore:
    def __init__(self, url: str, service_role_key: str, timeout: int = 15):
        self.url = (url or "").strip().rstrip("/")
        self.timeout = timeout
        if not self.url.startswith("https://") or not service_role_key:
            raise ValueError("Valid SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        self.headers = {
            "apikey": service_role_key,
            "Authorization": "Bearer " + service_role_key,
            "Content-Type": "application/json",
        }

    def _post(self, table: str, rows: list[dict], conflict: str | None = None):
        if not rows:
            return
        params = {"on_conflict": conflict} if conflict else {}
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
        try:
            response = requests.post(
                f"{self.url}/rest/v1/{table}", params=params, headers=headers,
                json=rows, timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = getattr(getattr(exc, "response", None), "text", "")[:300]
            raise BitpandaStoreError("Supabase write failed: " + (detail or str(exc))) from exc

    def save_sync(self, holdings: list[dict], operations: list[dict],
                  histories: dict[str, list[dict]], earn_configs: list[dict],
                  status: str = "success", error: str | None = None) -> str:
        observed = datetime.now(timezone.utc).isoformat()
        run = [{
            "status": status, "observed_at": observed,
            "holdings_count": len(holdings), "operations_count": len(operations),
            "earn_configs_count": len(earn_configs), "error": error,
        }]
        self._post("bitpanda_sync_runs", run)

        holding_rows = []
        for item in holdings:
            asset = item.get("asset") if isinstance(item.get("asset"), dict) else {}
            money = item.get("value") if isinstance(item.get("value"), dict) else {}
            holding_rows.append({
                "asset_id": str(item.get("assetId") or item.get("asset_id") or asset.get("id") or item.get("id") or "unknown"),
                "symbol": item.get("symbol") or asset.get("symbol"),
                "name": item.get("name") or asset.get("name"),
                "quantity": item.get("quantity") or item.get("amount"),
                "value_eur": money.get("value") if money else (item.get("valueEur") or item.get("value_eur")),
                "observed_at": observed, "raw_data": item,
            })
        self._post("bitpanda_holdings_snapshots", holding_rows, "asset_id,observed_at")

        operation_rows = []
        for item in operations:
            operation_id = item.get("id") or item.get("operationId") or item.get("operation_id")
            if not operation_id:
                continue
            operation_rows.append({
                "operation_id": str(operation_id),
                "operation_type": item.get("type") or item.get("operationType"),
                "status": item.get("status"),
                "asset_id": str(item.get("assetId") or item.get("asset_id") or ""),
                "symbol": item.get("symbol"),
                "occurred_at": item.get("createdAt") or item.get("timestamp") or item.get("date"),
                "raw_data": item,
            })
        self._post("bitpanda_operations", operation_rows, "operation_id")

        history_rows = []
        for timeframe, points in histories.items():
            for point in points:
                value = point.get("value")
                if isinstance(value, dict):
                    value = value.get("value")
                history_rows.append({
                    "timeframe": timeframe,
                    "observed_at": point.get("time") or point.get("timestamp") or observed,
                    "value_eur": value,
                    "raw_data": point,
                })
        self._post("bitpanda_portfolio_history", history_rows, "timeframe,observed_at")

        earn_rows = []
        for item in earn_configs:
            config_id = item.get("id") or item.get("configId")
            if not config_id:
                continue
            earn_rows.append({
                "config_id": str(config_id),
                "asset_id": str(item.get("assetId") or item.get("asset_id") or ""),
                "apr": item.get("annualPercentageRate") or item.get("annual_percentage_rate"),
                "product_type": item.get("type"),
                "mode": item.get("mode"),
                "enabled": item.get("enabled"),
                "soldout": item.get("soldout"),
                "observed_at": observed, "raw_data": item,
            })
        self._post("bitpanda_earn_configs", earn_rows, "config_id")
        return observed
