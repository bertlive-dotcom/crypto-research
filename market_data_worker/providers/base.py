"""Provider contract shared by market-data ingestion adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class MarketDataProviderError(RuntimeError):
    """Sanitized provider failure; never include credentials in the message."""


@dataclass(frozen=True)
class ProviderCapabilities:
    asset_classes: frozenset[str]
    quote_modes: frozenset[str] = frozenset()
    intervals: frozenset[str] = frozenset()
    realtime: bool = False
    websocket: bool = False
    venues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    healthy: bool
    checked_at: str
    latency_ms: float | None = None
    rate_limit_remaining: int | None = None
    error_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class MarketDataProvider(Protocol):
    """Read-only provider interface; implementations must declare entitlements."""

    name: str
    capabilities: ProviderCapabilities

    def health_check(self) -> ProviderHealth:
        ...

    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        ...

    def fetch_candles(
        self, symbol: str, interval: str, limit: int
    ) -> list[dict[str, Any]]:
        ...

    def fetch_fundamentals(self, symbol: str) -> list[dict[str, Any]]:
        ...
