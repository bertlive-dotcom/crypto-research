import unittest
from datetime import datetime, timedelta, timezone

from assistant.instruments import (
    AmbiguousInstrumentError, Instrument, InstrumentNotFoundError,
    InstrumentRegistry, initial_registry,
)
from assistant.market_data import validate_closed_candle, validate_quote


class InstrumentRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = initial_registry()

    def test_resolves_canonical_symbol_and_provider_alias(self):
        btc = self.registry.resolve("BTCUSD")
        self.assertEqual(btc.instrument_id, "CRYPTO:BTC:USD")
        self.assertEqual(self.registry.resolve("BTCUSDT", provider="binance"), btc)

    def test_provider_alias_is_not_guessed(self):
        with self.assertRaises(InstrumentNotFoundError):
            self.registry.resolve("BTCUSDT")
        with self.assertRaises(InstrumentNotFoundError):
            self.registry.resolve("XAUUSD", provider="binance")

    def test_gold_is_pending_and_not_enabled(self):
        gold = self.registry.resolve("XAUUSD")
        self.assertEqual(gold.coverage_status, "pending_verification")
        self.assertFalse(gold.enabled)
        self.assertIsNone(gold.provider_symbol("financialdata.net"))

    def test_only_verified_instruments_can_be_enabled(self):
        with self.assertRaisesRegex(ValueError, "only verified"):
            Instrument(
                instrument_id="COMMODITY:XAU:USD", asset_class="commodity",
                canonical_symbol="XAUUSD", display_name="Gold",
                quote_currency="USD", venue="OTC",
                coverage_status="pending_verification", enabled=True,
            )

    def test_duplicate_ids_are_rejected(self):
        item = self.registry.get("CRYPTO:BTC:USD")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.registry.register(item)

    def test_ambiguous_provider_symbol_requires_disambiguation(self):
        registry = InstrumentRegistry([
            Instrument("EQUITY:NYSE:ABC", "equity", "ABC", "ABC Inc",
                       "USD", "NYSE", (("vendor_a", "ABC"),), "verified", True),
            Instrument("EQUITY:NASDAQ:ABC", "equity", "ABC", "ABC Corp",
                       "USD", "NASDAQ", (("vendor_b", "ABC"),), "verified", True),
        ])
        with self.assertRaises(AmbiguousInstrumentError):
            registry.resolve("ABC")
        self.assertEqual(registry.resolve("ABC", provider="vendor_a").venue, "NYSE")


class MarketDataQualityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)

    def test_accepts_fresh_quote_with_timezone(self):
        quote = {
            "symbol": "BTCUSD", "asset_class": "crypto", "price": 90000,
            "currency": "USD", "source": "test",
            "observed_at": (self.now - timedelta(seconds=10)).isoformat(),
        }
        result = validate_quote(quote, max_age_seconds=60, now=self.now)
        self.assertTrue(result["usable"])
        self.assertEqual(result["price"], 90000)

    def test_rejects_stale_future_and_naive_quotes(self):
        base = {
            "symbol": "BTCUSD", "asset_class": "crypto", "price": 90000,
            "currency": "USD", "source": "test",
        }
        stale = validate_quote(
            {**base, "observed_at": (self.now - timedelta(minutes=5)).isoformat()},
            max_age_seconds=60, now=self.now,
        )
        future = validate_quote(
            {**base, "observed_at": (self.now + timedelta(minutes=2)).isoformat()},
            max_age_seconds=60, now=self.now,
        )
        naive = validate_quote(
            {**base, "observed_at": "2026-11-13T12:00:00"},
            max_age_seconds=60, now=self.now,
        )
        self.assertIn("stale_market_data", stale["reasons"])
        self.assertIn("future_market_data", future["reasons"])
        self.assertIn("invalid_observed_at", naive["reasons"])

    def test_missing_fields_and_invalid_price_fail_closed(self):
        result = validate_quote(
            {"symbol": "X", "observed_at": self.now.isoformat(), "price": float("nan")},
            max_age_seconds=60, now=self.now,
        )
        self.assertFalse(result["usable"])
        self.assertIn("missing_source", result["reasons"])
        self.assertIn("invalid_price", result["reasons"])

    def test_accepts_only_closed_valid_candles(self):
        candle = {
            "symbol": "BTCUSDT", "asset_class": "crypto", "source": "binance",
            "interval": "1h", "open": 100, "high": 110, "low": 95, "close": 105,
            "close_timestamp": (self.now - timedelta(minutes=1)).isoformat(),
        }
        result = validate_closed_candle(candle, now=self.now, max_age_seconds=3600)
        self.assertTrue(result["usable"])

    def test_rejects_open_stale_and_malformed_candles(self):
        base = {
            "symbol": "BTCUSDT", "asset_class": "crypto", "source": "binance",
            "interval": "1h", "open": 100, "high": 110, "low": 95, "close": 105,
        }
        opened = validate_closed_candle(
            {**base, "close_timestamp": (self.now + timedelta(minutes=1)).isoformat()},
            now=self.now, max_age_seconds=3600,
        )
        stale = validate_closed_candle(
            {**base, "close_timestamp": (self.now - timedelta(days=1)).isoformat()},
            now=self.now, max_age_seconds=3600,
        )
        malformed = validate_closed_candle(
            {**base, "high": 90, "close_timestamp": self.now.isoformat()},
            now=self.now, max_age_seconds=3600,
        )
        self.assertIn("candle_not_closed", opened["reasons"])
        self.assertIn("stale_candle", stale["reasons"])
        self.assertIn("inconsistent_ohlc", malformed["reasons"])


if __name__ == "__main__":
    unittest.main()
