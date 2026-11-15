"""Provider-neutral contracts for read-only equity and ETF research.

The contracts deliberately contain no provider SDK, persistence, UI, or
trading dependencies. Missing optional evidence remains unknown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    asset_class: str = "equity"
    exchange: str | None = None
    currency: str | None = None
    international: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("instrument symbol is required")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("instrument name is required")
        if self.asset_class not in {"equity", "etf"}:
            raise ValueError("asset_class must be equity or etf")


@dataclass(frozen=True)
class AnalysisRequest:
    instruments: tuple[Instrument, ...]
    history_limit: int = 120
    max_age_seconds: int = 5 * 86400
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.instruments:
            raise ValueError("at least one instrument is required")
        if not 1 <= self.history_limit <= 300:
            raise ValueError("history_limit must be between 1 and 300")
        if self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")
        symbols = [item.symbol.upper() for item in self.instruments]
        if len(symbols) != len(set(symbols)):
            raise ValueError("instrument symbols must be unique")


@dataclass(frozen=True)
class AnalysisResult:
    contract_version: str
    requested_at: str
    observed_at: str
    source: str
    instruments_requested: int
    analyses: tuple[dict[str, Any], ...]
    unavailable: tuple[dict[str, Any], ...]
    quality: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the response."""
        return {
            "contract_version": self.contract_version,
            "requested_at": self.requested_at,
            "observed_at": self.observed_at,
            "source": self.source,
            "instruments_requested": self.instruments_requested,
            "analyses": [dict(item) for item in self.analyses],
            "unavailable": [dict(item) for item in self.unavailable],
            "quality": [dict(item) for item in self.quality],
        }
