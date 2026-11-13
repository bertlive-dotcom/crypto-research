"""Canonical instrument identity and explicit provider alias resolution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


ASSET_CLASSES = frozenset({
    "equity", "etf", "index", "crypto", "forex", "commodity", "future",
})
COVERAGE_STATES = frozenset({
    "verified", "adapter_available_unverified_entitlement",
    "pending_verification", "unavailable",
})


@dataclass(frozen=True)
class Instrument:
    """One economic instrument, independent of provider-native ticker aliases."""

    instrument_id: str
    asset_class: str
    canonical_symbol: str
    display_name: str
    quote_currency: str
    venue: str
    provider_symbols: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    coverage_status: str = "pending_verification"
    enabled: bool = False
    session_type: str = "unknown"
    contract_multiplier: float | None = None

    def __post_init__(self) -> None:
        required = (
            self.instrument_id, self.asset_class, self.canonical_symbol,
            self.display_name, self.quote_currency, self.venue,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("instrument identity fields must be non-empty")
        if self.asset_class not in ASSET_CLASSES:
            raise ValueError(f"unsupported asset class: {self.asset_class}")
        if self.coverage_status not in COVERAGE_STATES:
            raise ValueError(f"unsupported coverage status: {self.coverage_status}")
        if self.contract_multiplier is not None and self.contract_multiplier <= 0:
            raise ValueError("contract_multiplier must be positive")
        providers = [provider.lower() for provider, _ in self.provider_symbols]
        if len(providers) != len(set(providers)):
            raise ValueError("provider aliases must be unique per instrument")
        if any(not provider.strip() or not symbol.strip()
               for provider, symbol in self.provider_symbols):
            raise ValueError("provider aliases must be non-empty")
        if self.enabled and self.coverage_status != "verified":
            raise ValueError("only verified instruments can be enabled")

    def provider_symbol(self, provider: str) -> str | None:
        provider = provider.strip().lower()
        return next(
            (symbol for name, symbol in self.provider_symbols
             if name.lower() == provider),
            None,
        )


class InstrumentNotFoundError(LookupError):
    """No exact canonical instrument or provider alias was found."""


class AmbiguousInstrumentError(LookupError):
    """A provider alias maps to more than one canonical instrument."""


class InstrumentRegistry:
    """In-memory registry; callers supply records from reviewed configuration."""

    def __init__(self, instruments: Iterable[Instrument] = ()) -> None:
        self._by_id: dict[str, Instrument] = {}
        for instrument in instruments:
            self.register(instrument)

    def register(self, instrument: Instrument) -> None:
        key = instrument.instrument_id.upper()
        if key in self._by_id:
            raise ValueError(f"duplicate instrument_id: {instrument.instrument_id}")
        self._by_id[key] = instrument

    def get(self, instrument_id: str) -> Instrument:
        try:
            return self._by_id[instrument_id.strip().upper()]
        except (KeyError, AttributeError) as exc:
            raise InstrumentNotFoundError(instrument_id) from exc

    def resolve(
        self, symbol: str, *, provider: str | None = None,
        asset_class: str | None = None,
    ) -> Instrument:
        """Resolve exact IDs/symbols only; never infer or substitute a ticker."""
        query = symbol.strip().upper()
        provider_key = provider.strip().lower() if provider else None
        matches = []
        for instrument in self._by_id.values():
            if asset_class and instrument.asset_class != asset_class.lower():
                continue
            canonical_match = query in {
                instrument.instrument_id.upper(),
                instrument.canonical_symbol.upper(),
            }
            provider_match = provider_key and any(
                name.lower() == provider_key and alias.upper() == query
                for name, alias in instrument.provider_symbols
            )
            if canonical_match or provider_match:
                matches.append(instrument)
        if not matches:
            raise InstrumentNotFoundError(symbol)
        if len(matches) > 1:
            raise AmbiguousInstrumentError(
                f"{symbol!r} matches multiple instruments; specify provider or asset_class"
            )
        return matches[0]

    def enabled(self) -> list[Instrument]:
        return sorted(
            (item for item in self._by_id.values() if item.enabled),
            key=lambda item: (item.asset_class, item.canonical_symbol),
        )


def initial_registry() -> InstrumentRegistry:
    """Conservative seed records; XAUUSD is deliberately disabled pending verification."""
    return InstrumentRegistry([
        Instrument(
            instrument_id="CRYPTO:BTC:USD", asset_class="crypto",
            canonical_symbol="BTCUSD", display_name="Bitcoin / US Dollar",
            quote_currency="USD", venue="multi-venue",
            provider_symbols=(("binance", "BTCUSDT"),),
            coverage_status="adapter_available_unverified_entitlement",
            session_type="24x7",
        ),
        Instrument(
            instrument_id="EQUITY:NASDAQ:NVDA", asset_class="equity",
            canonical_symbol="NVDA", display_name="NVIDIA",
            quote_currency="USD", venue="NASDAQ",
            provider_symbols=(("twelve_data", "NVDA"),
                              ("financialdata.net", "NVDA")),
            coverage_status="adapter_available_unverified_entitlement",
            session_type="exchange",
        ),
        Instrument(
            instrument_id="ETF:NYSEARCA:SPY", asset_class="etf",
            canonical_symbol="SPY", display_name="SPDR S&P 500 ETF Trust",
            quote_currency="USD", venue="NYSE Arca",
            provider_symbols=(("twelve_data", "SPY"),
                              ("financialdata.net", "SPY")),
            coverage_status="adapter_available_unverified_entitlement",
            session_type="exchange",
        ),
        Instrument(
            instrument_id="FOREX:EUR:USD", asset_class="forex",
            canonical_symbol="EURUSD", display_name="Euro / US Dollar",
            quote_currency="USD", venue="OTC FX",
            provider_symbols=(("alpha_vantage", "EURUSD"),),
            coverage_status="adapter_available_unverified_entitlement",
            session_type="24x5",
        ),
        Instrument(
            instrument_id="COMMODITY:XAU:USD", asset_class="commodity",
            canonical_symbol="XAUUSD", display_name="Gold spot / US Dollar",
            quote_currency="USD", venue="OTC spot",
            provider_symbols=(),
            coverage_status="pending_verification",
            enabled=False, session_type="provider_dependent",
        ),
    ])
