"""Provider-neutral read-only analysis orchestration for equities and ETFs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from global_markets.market_analysis import analyze_candles

from .contracts import AnalysisRequest, AnalysisResult, CONTRACT_VERSION


class DailyMarketDataProvider(Protocol):
    """Minimum adapter contract required by the analysis service."""

    def fetch_daily_prices_with_quality(
        self,
        symbol: str,
        asset_class: str,
        *,
        international: bool,
        limit: int,
    ) -> dict[str, Any]:
        ...


class EquityAnalysisService:
    """Run deterministic technical analysis without UI or trading side effects."""

    def __init__(self, provider: DailyMarketDataProvider, source: str) -> None:
        if not source or not source.strip():
            raise ValueError("source is required")
        self.provider = provider
        self.source = source.strip()

    def analyze(
        self,
        request: AnalysisRequest,
        *,
        now: datetime | None = None,
    ) -> AnalysisResult:
        observed_at = now or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        analyses: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        quality: list[dict[str, Any]] = []

        for instrument in request.instruments:
            try:
                feed = self.provider.fetch_daily_prices_with_quality(
                    instrument.symbol,
                    instrument.asset_class,
                    international=instrument.international,
                    limit=request.history_limit,
                )
                candles = feed.get("candles")
                rejected = feed.get("rejected_records")
                if not isinstance(candles, list) or not isinstance(rejected, list):
                    raise ValueError("provider returned an invalid normalized feed")

                analysis = analyze_candles(
                    candles,
                    now=observed_at,
                    max_age_seconds=request.max_age_seconds,
                )
                analysis.update({
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "asset_class": instrument.asset_class,
                    "exchange": instrument.exchange,
                    "currency": instrument.currency,
                    "source": self.source,
                    "source_records": feed.get("source_records"),
                    "valid_records": len(candles),
                    "rejected_records": len(rejected),
                })
                analyses.append(analysis)

                if rejected:
                    quality.append({
                        "symbol": instrument.symbol,
                        "rejected_records": len(rejected),
                        "examples": [
                            {
                                "date": row.get("date"),
                                "reason": row.get("reason"),
                            }
                            for row in rejected[:3]
                            if isinstance(row, dict)
                        ],
                    })
            except Exception as error:
                # Do not leak raw provider exception text (which can contain
                # request URLs or credentials) into the public analysis result.
                unavailable.append({
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "status": "unavailable",
                    "error_type": type(error).__name__,
                    "reason": "provider_or_normalization_error",
                })

        analyses.sort(
            key=lambda row: (
                bool(row.get("eligible")),
                row.get("technical_screen_score")
                if row.get("technical_screen_score") is not None else -1,
            ),
            reverse=True,
        )
        return AnalysisResult(
            contract_version=CONTRACT_VERSION,
            requested_at=request.requested_at.astimezone(timezone.utc).isoformat(),
            observed_at=observed_at.astimezone(timezone.utc).isoformat(),
            source=self.source,
            instruments_requested=len(request.instruments),
            analyses=tuple(analyses),
            unavailable=tuple(unavailable),
            quality=tuple(quality),
        )
