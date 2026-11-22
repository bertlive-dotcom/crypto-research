import unittest
from datetime import datetime, timedelta, timezone

try:
    import numpy as np
except ImportError:
    raise unittest.SkipTest("NumPy is required for portfolio-engine tests")

from portfolio_engine.data.binance_history import (
    BINANCE_SPOT_PAIRS,
    fetch_daily_close_series,
    forecast_watchlist_from_binance,
)


class FakeBinanceClient:
    def __init__(self, listings=None, candles=None):
        self.listings = listings if listings is not None else {
            pair: {"status": "TRADING", "spot_allowed": True}
            for pair in BINANCE_SPOT_PAIRS.values()
        }
        self.candles = candles or {}
        self.calls = []

    def get_spot_symbol_status(self):
        return self.listings

    def get_klines(self, symbol, interval="1d", limit=500):
        self.calls.append((symbol, interval, limit))
        return self.candles.get(symbol, [])


def make_candles(count=140, *, now=None):
    now = now or datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    first = now.date() - timedelta(days=count)
    rows = []
    for offset in range(count):
        day = first + timedelta(days=offset)
        close_time = datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc)
        rows.append({
            "date": day.isoformat(), "close_timestamp": close_time.isoformat(),
            "close": 100.0 + offset * 0.2 + np.sin(offset / 4.0),
        })
    return rows


class BinanceHistoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)

    def test_fetches_closed_daily_series_without_open_candle(self):
        rows = make_candles(now=self.now)
        rows.append({
            "date": "2026-11-22", "close_timestamp": "2026-11-22T23:59:59.999+00:00",
            "close": 999.0,
        })
        client = FakeBinanceClient(candles={"BTCUSDT": rows})
        result = fetch_daily_close_series(
            ["BTCUSD"], client=client, min_observations=120, now=self.now,
        )
        series = result["series"]["BTCUSD"]
        self.assertEqual(series["observations"], 140)
        self.assertNotIn("2026-11-22", series["dates"])
        self.assertEqual(client.calls, [("BTCUSDT", "1d", 1000)])
        self.assertTrue(result["read_only"])

    def test_rejects_unlisted_pair_without_fallback(self):
        client = FakeBinanceClient(listings={})
        result = fetch_daily_close_series(["XMRUSD"], client=client, now=self.now)
        self.assertEqual(result["series"], {})
        self.assertEqual(result["unavailable"][0]["reason"], "pair_not_listed_on_binance_spot")
        self.assertEqual(client.calls, [])

    def test_rejects_pair_not_enabled_for_spot(self):
        client = FakeBinanceClient(listings={
            "XMRUSDT": {"status": "BREAK", "spot_allowed": True}
        })
        result = fetch_daily_close_series(["XMRUSD"], client=client, now=self.now)
        self.assertEqual(result["unavailable"][0]["reason"], "pair_not_active_for_spot_trading")

    def test_rejects_insufficient_history(self):
        client = FakeBinanceClient(candles={"ANVLUSDT": make_candles(80, now=self.now)})
        result = fetch_daily_close_series(
            ["ANVLUSD"], client=client, min_observations=120, now=self.now,
        )
        self.assertEqual(result["unavailable"][0]["reason"], "insufficient_closed_daily_history")

    def test_rejects_missing_calendar_day(self):
        rows = make_candles(now=self.now)
        rows.pop(30)
        client = FakeBinanceClient(candles={"ETHUSDT": rows})
        result = fetch_daily_close_series(["ETHUSD"], client=client, now=self.now)
        self.assertEqual(result["unavailable"][0]["reason"], "history_fetch_or_validation_failed")
        self.assertEqual(result["series"], {})

    def test_unknown_symbol_is_reported_not_substituted(self):
        client = FakeBinanceClient()
        result = fetch_daily_close_series(["UNKNOWNUSD"], client=client, now=self.now)
        self.assertEqual(result["unavailable"][0]["reason"], "no_binance_pair_mapping")
        self.assertEqual(client.calls, [])

    def test_forecast_runner_reports_calibration_and_eligibility(self):
        client = FakeBinanceClient(candles={"BTCUSDT": make_candles(180, now=self.now)})
        result = forecast_watchlist_from_binance(
            ["BTCUSD"], client=client, min_observations=120, now=self.now,
        )
        forecast = result["forecasts"]["BTCUSD"]
        self.assertEqual(forecast["horizon_days"], 7)
        self.assertGreater(forecast["walk_forward_validation_count"], 0)
        self.assertIn("view_eligible", forecast)
        self.assertEqual(result["summary"]["forecasted"], 1)
        self.assertTrue(result["read_only"])


if __name__ == "__main__":
    unittest.main()
