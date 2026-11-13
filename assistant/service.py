"""Read-only application service shared by Streamlit and messaging adapters.

The service accepts normalized market-feed data and returns serializable research
summaries. It never creates trade proposals, mutates portfolios, or executes orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from global_markets.crypto_feed import BINANCE_SPOT_PAIRS
from global_markets.market_analysis import analyze_candles, classify_timeframe_structure


class FeedProtocol(Protocol):
    def fetch(self, symbols=None, intervals=("1d", "4h"), limit=200) -> dict: ...


class AssistantServiceError(RuntimeError):
    """Raised when the market feed cannot produce a usable report."""


class ReadOnlyAssistantService:
    """Shared read-only market analysis facade; feed is injectable for tests."""

    def __init__(self, feed: FeedProtocol):
        self.feed = feed

    def crypto_overview(
        self,
        symbols: list[str] | None = None,
        *,
        now: datetime | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        requested = [item.upper() for item in (symbols or list(BINANCE_SPOT_PAIRS))]
        unknown = [item for item in requested if item not in BINANCE_SPOT_PAIRS]
        if unknown:
            raise ValueError("Unsupported canonical crypto symbols: " + ", ".join(unknown))
        if len(requested) != len(set(requested)):
            raise ValueError("symbols must be unique")
        if not 35 <= limit <= 1000:
            raise ValueError("limit must be between 35 and 1000")

        try:
            payload = self.feed.fetch(requested, intervals=("1d", "4h"), limit=limit)
        except Exception as exc:
            raise AssistantServiceError("Market data feed request failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise AssistantServiceError("Market data feed returned an invalid payload")

        rows_by_pair: dict[str, list[dict]] = {}
        for row in payload["data"]:
            if not isinstance(row, dict):
                continue
            pair = str(row.get("symbol", "")).upper()
            rows_by_pair.setdefault(pair, []).append(row)

        analyses: dict[str, dict[str, dict]] = {}
        for canonical in requested:
            pair = BINANCE_SPOT_PAIRS[canonical]
            pair_rows = rows_by_pair.get(pair, [])
            analyses[canonical] = {}
            for interval in ("1d", "4h"):
                candles = [row for row in pair_rows if row.get("interval") == interval]
                analyses[canonical][interval] = analyze_candles(candles, now=now)

        btc_daily = analyses.get("BTCUSD", {}).get("1d")
        btc_return = (btc_daily or {}).get("indicators", {}).get("return_30d_pct") if (btc_daily or {}).get("eligible") else None
        instruments = []
        for canonical in requested:
            daily = analyses[canonical]["1d"]
            tactical = analyses[canonical]["4h"]
            structure = classify_timeframe_structure(daily, tactical)
            daily_indicators = daily.get("indicators", {}) if daily.get("eligible") else {}
            relative_strength = None
            asset_return = daily_indicators.get("return_30d_pct")
            if asset_return is not None and btc_return is not None:
                relative_strength = round(asset_return - btc_return, 2)
            instruments.append({
                "symbol": canonical,
                "provider_symbol": BINANCE_SPOT_PAIRS[canonical],
                "asset_class": "crypto",
                "daily": daily,
                "tactical_4h": tactical,
                "structure": structure,
                "relative_strength_vs_btc_30d_pp": relative_strength,
                "read_only": True,
            })

        eligible = sum(
            1 for item in instruments
            if item["daily"].get("eligible") and item["tactical_4h"].get("eligible")
        )
        unavailable = payload.get("unavailable", [])
        generated_at = now or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        return {
            "schema_version": "1.0",
            "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
            "source": payload.get("source", "unknown"),
            "read_only": True,
            "mode": "research_only",
            "summary": {
                "requested": len(requested),
                "with_both_timeframes": eligible,
                "incomplete": len(requested) - eligible,
                "unavailable_feed_requests": len(unavailable),
                "technical_score_warning": "Technical screening only; not probability, expected return, or investment advice.",
            },
            "instruments": instruments,
            "unavailable": unavailable,
        }
