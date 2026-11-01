"""Crypto watchlist feed backed by Binance public spot market data.

This is a read-only data integration. It does not touch the legacy scanner,
paper ledger, exchange account endpoints, or order execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .config import DEFAULT_UNIVERSE_SEEDS
from .providers.binance import BinanceMarketDataClient, BinanceMarketDataError

# Canonical watchlist symbol -> Binance spot symbol. Availability is checked
# at request time; unsupported pairs are reported rather than silently replaced.
BINANCE_SPOT_PAIRS = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "SOLUSD": "SOLUSDT",
    "LINKUSD": "LINKUSDT",
    "XLMUSD": "XLMUSDT",
    "SUIUSD": "SUIUSDT",
    "HYPEUSD": "HYPEUSDT",
    "XMRUSD": "XMRUSDT",
    "LEOUSD": "LEOUSDT",
    "BATUSD": "BATUSDT",
    "PEPEUSD": "PEPEUSDT",
    "BEAMUSD": "BEAMUSDT",
    "ANVLUSD": "ANVLUSDT",
}


class CryptoWatchlistFeed:
    def __init__(self, client: BinanceMarketDataClient | None = None):
        self.client = client or BinanceMarketDataClient()

    def fetch(self, symbols: Iterable[str] | None = None,
              intervals: tuple[str, ...] = ("1d", "4h"),
              limit: int = 200) -> dict:
        """Fetch available watchlist pairs, preserving per-pair failures."""
        requested = list(symbols) if symbols is not None else list(DEFAULT_UNIVERSE_SEEDS["crypto"])
        data, unavailable = [], []
        observed_at = datetime.now(timezone.utc).isoformat()
        try:
            symbol_status = self.client.get_spot_symbol_status()
        except BinanceMarketDataError as exc:
            return {
                "source": "binance", "observed_at": observed_at, "read_only": True,
                "requested_symbols": requested, "intervals": list(intervals), "data": [],
                "unavailable": [{"symbol": symbol, "reason": "spot_listing_check_failed: " + str(exc)}
                                for symbol in requested],
                "summary": {"requested": len(requested), "returned_pairs": 0,
                            "observations": 0, "unavailable_requests": len(requested) * len(intervals),
                            "availability_counts": {"listing_check_failed": len(requested) * len(intervals)}},
            }
        reason_counts = {}
        for canonical in requested:
            pair = BINANCE_SPOT_PAIRS.get(canonical.upper())
            if not pair:
                for interval in intervals:
                    unavailable.append({"symbol": canonical, "interval": interval, "reason": "no_binance_pair_mapping"})
                    reason_counts["no_binance_pair_mapping"] = reason_counts.get("no_binance_pair_mapping", 0) + 1
                continue
            listing = symbol_status.get(pair)
            if listing is None:
                reason = "pair_not_listed_on_binance_spot"
            elif listing.get("status") != "TRADING":
                reason = "pair_not_trading_on_binance_spot"
            elif not listing.get("spot_allowed"):
                reason = "spot_trading_not_allowed_for_pair"
            else:
                reason = None
            if reason:
                for interval in intervals:
                    unavailable.append({
                        "symbol": canonical, "provider_symbol": pair,
                        "interval": interval, "reason": reason,
                    })
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                continue
            for interval in intervals:
                    unavailable.append({
                        "symbol": canonical, "provider_symbol": pair,
                        "interval": interval, "reason": "pair_not_currently_trading_on_binance_spot",
                    })
                continue
            for interval in intervals:
                try:
                    rows = self.client.get_klines(pair, interval=interval, limit=limit)
                    data.extend(rows)
                except (BinanceMarketDataError, ValueError) as exc:
                    unavailable.append({
                        "symbol": canonical,
                        "provider_symbol": pair,
                        "interval": interval,
                        "reason": str(exc),
                    })
        return {
            "source": "binance",
            "observed_at": observed_at,
            "read_only": True,
            "requested_symbols": requested,
            "intervals": list(intervals),
            "data": data,
            "unavailable": unavailable,
            "summary": {
                "requested": len(requested),
                "returned_pairs": len({row["symbol"] for row in data}),
                "observations": len(data),
                "unavailable_requests": len(unavailable),
            },
        }
