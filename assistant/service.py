"""Read-only application service shared by Streamlit and messaging adapters.

The service composes existing market feeds and analysis primitives. It never
creates trade proposals, mutates portfolios, or executes orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from global_markets.crypto_feed import BINANCE_SPOT_PAIRS
from global_markets.market_analysis import analyze_candles, classify_timeframe_structure
from global_markets.providers.financialdata import FinancialDataError
from .instruments import InstrumentRegistry, initial_registry


class FeedProtocol(Protocol):
    def fetch(self, symbols=None, intervals=("1d", "4h"), limit=200) -> dict: ...


class AssistantServiceError(RuntimeError):
    """Raised when a market feed cannot produce a usable report."""


class ReadOnlyAssistantService:
    """Shared read-only facade with injectable, provider-specific adapters."""

    def __init__(self, feed: FeedProtocol | None = None, *, financialdata_client: Any | None = None,
                 alphavantage_client: Any | None = None, registry: InstrumentRegistry | None = None):
        self.feed = feed
        self.financialdata_client = financialdata_client
        self.alphavantage_client = alphavantage_client
        self.registry = registry or initial_registry()

    @staticmethod
    def _generated_at(now: datetime | None) -> str:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def crypto_overview(self, symbols: list[str] | None = None, *, now: datetime | None = None,
                        limit: int = 200) -> dict[str, Any]:
        if self.feed is None:
            raise AssistantServiceError("Crypto market feed is not configured")
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
            raise AssistantServiceError("Crypto market data feed request failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise AssistantServiceError("Crypto market data feed returned an invalid payload")

        rows_by_pair: dict[str, list[dict]] = {}
        for row in payload["data"]:
            if isinstance(row, dict):
                rows_by_pair.setdefault(str(row.get("symbol", "")).upper(), []).append(row)
        analyses = {}
        for canonical in requested:
            pair_rows = rows_by_pair.get(BINANCE_SPOT_PAIRS[canonical], [])
            analyses[canonical] = {
                interval: analyze_candles([row for row in pair_rows if row.get("interval") == interval], now=now)
                for interval in ("1d", "4h")
            }
        btc_daily = analyses.get("BTCUSD", {}).get("1d")
        btc_return = btc_daily.get("indicators", {}).get("return_30d_pct") if btc_daily and btc_daily.get("eligible") else None
        instruments = []
        for canonical in requested:
            daily, tactical = analyses[canonical]["1d"], analyses[canonical]["4h"]
            asset_return = daily.get("indicators", {}).get("return_30d_pct") if daily.get("eligible") else None
            relative_strength = round(asset_return - btc_return, 2) if asset_return is not None and btc_return is not None else None
            instruments.append({
                "symbol": canonical, "provider_symbol": BINANCE_SPOT_PAIRS[canonical],
                "asset_class": "crypto", "coverage_status": "adapter_available_unverified_entitlement",
                "daily": daily, "tactical_4h": tactical,
                "structure": classify_timeframe_structure(daily, tactical),
                "relative_strength_vs_btc_30d_pp": relative_strength, "read_only": True,
            })
        eligible = sum(1 for item in instruments if item["daily"].get("eligible") and item["tactical_4h"].get("eligible"))
        unavailable = payload.get("unavailable", [])
        return {
            "schema_version": "1.1", "generated_at": self._generated_at(now),
            "source": payload.get("source", "unknown"), "read_only": True, "mode": "research_only",
            "summary": {
                "requested": len(requested), "with_both_timeframes": eligible,
                "incomplete": len(requested) - eligible, "unavailable_feed_requests": len(unavailable),
                "technical_score_warning": "Technical screening only; not probability, expected return, or investment advice.",
            },
            "instruments": instruments, "unavailable": unavailable,
        }

    def daily_multi_asset_overview(self, symbols: list[str], *, now: datetime | None = None,
                                   limit: int = 120) -> dict[str, Any]:
        """Analyze explicitly mapped daily equities, ETFs and FX; no ticker guessing.

        Provider adapter availability is not proof of subscription entitlement.
        Unverified observations remain research-only until separately reviewed.
        """
        if not symbols:
            raise ValueError("at least one symbol is required")
        requested = [item.strip().upper() for item in symbols]
        if any(not item for item in requested) or len(requested) != len(set(requested)):
            raise ValueError("symbols must be non-empty and unique")
        if not 35 <= limit <= 300:
            raise ValueError("limit must be between 35 and 300")
        records, unavailable = [], []
        for symbol in requested:
            try:
                instrument = self.registry.resolve(symbol)
            except (LookupError, ValueError) as exc:
                raise ValueError(f"Instrument is not registered: {symbol}") from exc
            if instrument.coverage_status in {"pending_verification", "unavailable"}:
                raise ValueError(f"Instrument is not enabled for assistant research: {symbol}")
            providers = [name for name, _ in instrument.provider_symbols]
            rejected = []
            if instrument.asset_class in {"equity", "etf"}:
                provider = "financialdata.net"
                if provider not in providers or self.financialdata_client is None:
                    unavailable.append({"symbol": symbol, "reason": "financialdata_adapter_not_configured"})
                    continue
                try:
                    result = self.financialdata_client.fetch_daily_prices_with_quality(
                        instrument.provider_symbol(provider), instrument.asset_class, limit=limit
                    )
                    candles, rejected = result.get("candles", []), result.get("rejected_records", [])
                except Exception as exc:
                    failure = {
                        "symbol": symbol,
                        "reason": "financialdata_request_failed",
                        "error_type": type(exc).__name__,
                    }
                    # Only expose messages from our provider adapter's controlled
                    # exception type; arbitrary exception text may contain secrets.
                    if isinstance(exc, FinancialDataError):
                        failure["diagnostic"] = str(exc)
                    else:
                        failure["diagnostic"] = "Provider error; details withheld for credential safety."
                    unavailable.append(failure)
                    continue
            elif instrument.asset_class == "forex":
                provider = "alpha_vantage"
                if provider not in providers or self.alphavantage_client is None:
                    unavailable.append({"symbol": symbol, "reason": "alphavantage_adapter_not_configured"})
                    continue
                base, quote = instrument.canonical_symbol[:3], instrument.canonical_symbol[3:]
                try:
                    candles = self.alphavantage_client.get_fx_daily(base, quote)[-limit:]
                except Exception:
                    unavailable.append({"symbol": symbol, "reason": "alphavantage_request_failed"})
                    continue
            else:
                unavailable.append({"symbol": symbol, "reason": "daily_asset_class_not_enabled_in_assistant"})
                continue
            analysis = analyze_candles(candles, now=now)
            records.append({
                "symbol": instrument.canonical_symbol, "instrument_id": instrument.instrument_id,
                "asset_class": instrument.asset_class, "provider": provider,
                "provider_symbol": instrument.provider_symbol(provider),
                "coverage_status": instrument.coverage_status,
                "entitlement_verified": instrument.coverage_status == "verified",
                "analysis": analysis, "rejected_source_records": rejected, "read_only": True,
            })
        return {
            "schema_version": "1.1", "generated_at": self._generated_at(now),
            "source": "multi_provider_daily", "read_only": True, "mode": "research_only",
            "summary": {
                "requested": len(requested), "returned": len(records),
                "data_quality_eligible": sum(1 for item in records if item["analysis"].get("eligible")),
                "entitlement_verified": sum(1 for item in records if item["entitlement_verified"]),
                "unavailable": len(unavailable),
                "warning": "Provider adapter availability does not prove plan entitlement or data licensing. Unverified instruments remain research-only.",
            },
            "instruments": records, "unavailable": unavailable,
        }
