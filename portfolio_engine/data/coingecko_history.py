"""Read-only CoinGecko USD daily prices and market-cap inputs.

Requires COINGECKO_DEMO_API_KEY in the runtime environment. Uses one provider
for the full cross-section so assets are not mixed across quote currencies.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from typing import Any
import requests

BASE_URL = "https://api.coingecko.com/api/v3"
COINGECKO_IDS = {
    "BTCUSD": "bitcoin", "ETHUSD": "ethereum", "SOLUSD": "solana",
    "LINKUSD": "chainlink", "XLMUSD": "stellar", "SUIUSD": "sui",
    "HYPEUSD": "hyperliquid", "XMRUSD": "monero", "LEOUSD": "leo-token",
    "BATUSD": "basic-attention-token", "PEPEUSD": "pepe",
    "BEAMUSD": "beam-2", "ANVLUSD": "anvil",
}


class CoinGeckoHistoryClient:
    def __init__(self, *, api_key: str | None = None, session: Any | None = None,
                 timeout: float = 20.0, base_url: str = BASE_URL):
        self.api_key = api_key if api_key is not None else os.getenv("COINGECKO_DEMO_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict) -> dict:
        if not self.api_key:
            raise RuntimeError("COINGECKO_DEMO_API_KEY is not configured")
        try:
            response = self.session.get(
                f"{self.base_url}{path}", params=params,
                headers={"x-cg-demo-api-key": self.api_key}, timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                raise RuntimeError("CoinGecko rate limit reached") from exc
            raise RuntimeError("CoinGecko historical-data request failed") from exc
        except ValueError as exc:
            raise RuntimeError("CoinGecko returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("CoinGecko returned an unexpected response")
        return payload

    def get_daily_prices(self, coin_id: str, days: int = 365) -> list[dict]:
        if not 90 <= days <= 365:
            raise ValueError("days must be between 90 and 365 on the Demo plan")
        payload = self._get(f"/coins/{coin_id}/market_chart",
                            {"vs_currency": "usd", "days": days})
        prices = payload.get("prices")
        if not isinstance(prices, list) or not prices:
            raise RuntimeError("CoinGecko returned no price history")
        rows = []
        for item in prices:
            if not isinstance(item, list) or len(item) != 2:
                raise RuntimeError("CoinGecko returned malformed price history")
            timestamp, price = int(item[0]), float(item[1])
            if price <= 0 or not price < float("inf"):
                raise RuntimeError("CoinGecko returned a non-positive or non-finite price")
            date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
            rows.append({"date": date, "close": price})
        rows.sort(key=lambda item: item["date"])
        deduplicated = {}
        for row in rows:
            deduplicated[row["date"]] = row["close"]
        return [{"date": date, "close": close} for date, close in sorted(deduplicated.items())]

    def get_market_caps(self, coin_ids: list[str]) -> dict[str, float]:
        payload = self._get("/coins/markets", {
            "vs_currency": "usd", "ids": ",".join(coin_ids),
            "order": "market_cap_desc", "per_page": min(250, len(coin_ids)),
            "page": 1, "sparkline": "false",
        })
        if not isinstance(payload, list):
            raise RuntimeError("CoinGecko returned unexpected market-cap data")
        caps = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            coin_id, cap = item.get("id"), item.get("market_cap")
            if coin_id in coin_ids and cap is not None:
                value = float(cap)
                if value > 0 and value < float("inf"):
                    caps[coin_id] = value
        return caps


def fetch_watchlist_history(*, client: CoinGeckoHistoryClient | None = None,
                            days: int = 365, symbols: list[str] | None = None,
                            sleep_seconds: float = 0.15) -> dict:
    """Fetch one-source daily USD closes and current caps; keep per-asset failures."""
    client = client or CoinGeckoHistoryClient()
    requested = list(symbols or COINGECKO_IDS)
    if len(requested) != len(set(requested)):
        raise ValueError("symbols must be unique")
    observed_at = datetime.now(timezone.utc).isoformat()
    result = {"source": "coingecko", "quote_currency": "USD", "observed_at": observed_at,
              "read_only": True, "series": {}, "market_caps": {}, "unavailable": []}
    known_ids = [COINGECKO_IDS[s] for s in requested if s in COINGECKO_IDS]
    try:
        caps = client.get_market_caps(known_ids)
        result["market_caps"] = {
            symbol: caps[COINGECKO_IDS[symbol]] for symbol in requested
            if symbol in COINGECKO_IDS and COINGECKO_IDS[symbol] in caps
        }
    except Exception as exc:
        for symbol in requested:
            result["unavailable"].append({"symbol": symbol, "reason": "market_cap_fetch_failed", "detail": str(exc)})
        return result

    for index, symbol in enumerate(requested):
        coin_id = COINGECKO_IDS.get(symbol)
        if coin_id is None:
            result["unavailable"].append({"symbol": symbol, "reason": "no_coingecko_id_mapping"})
            continue
        try:
            rows = client.get_daily_prices(coin_id, days=days)
            if len(rows) < 120:
                raise ValueError("insufficient_daily_history")
            dates = [row["date"] for row in rows]
            result["series"][symbol] = {
                "provider_id": coin_id, "dates": dates,
                "closes": [row["close"] for row in rows],
                "observations": len(rows), "first_date": dates[0], "last_date": dates[-1],
            }
        except Exception as exc:
            reason = str(exc) if str(exc) == "insufficient_daily_history" else "history_fetch_or_validation_failed"
            result["unavailable"].append({"symbol": symbol, "provider_id": coin_id,
                                           "reason": reason, "detail": str(exc)})
        if index < len(requested) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)
    result["summary"] = {"requested": len(requested), "available": len(result["series"]),
                         "unavailable": len(result["unavailable"]),
                         "market_caps_available": len(result["market_caps"])}
    return result
