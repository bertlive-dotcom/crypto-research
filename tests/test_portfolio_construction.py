import unittest

try:
    import numpy as np
except ImportError:
    raise unittest.SkipTest("NumPy is required for portfolio-engine tests")

from portfolio_engine.analytics.portfolio import optimize_long_only
from portfolio_engine.data.coingecko_history import COINGECKO_IDS, CoinGeckoHistoryClient
from portfolio_engine.portfolio import align_common_history, build_portfolio_snapshot


class OptimizerTests(unittest.TestCase):
    def test_long_only_weights_respect_cap_and_sum_to_one(self):
        mu = np.array([0.08, 0.05, 0.03, 0.01])
        sigma = np.array([
            [0.04, 0.01, 0.01, 0.00],
            [0.01, 0.05, 0.01, 0.00],
            [0.01, 0.01, 0.06, 0.00],
            [0.00, 0.00, 0.00, 0.03],
        ])
        result = optimize_long_only(mu, sigma, risk_aversion=2.5, max_weight=0.35)
        self.assertAlmostEqual(float(result["weights"].sum()), 1.0, places=9)
        self.assertGreaterEqual(float(result["weights"].min()), 0.0)
        self.assertLessEqual(float(result["weights"].max()), 0.35 + 1e-9)
        self.assertTrue(result["converged"])
        self.assertGreater(result["expected_return"], 0.0)

    def test_rejects_infeasible_weight_cap(self):
        with self.assertRaises(ValueError):
            optimize_long_only([0.1, 0.2], np.eye(2), max_weight=0.4)

    def test_rejects_non_positive_definite_covariance(self):
        with self.assertRaises(ValueError):
            optimize_long_only([0.1, 0.2], [[1.0, 2.0], [2.0, 1.0]])


class DataAlignmentTests(unittest.TestCase):
    def test_aligns_all_assets_on_common_dates(self):
        series = {
            "BTCUSD": {"dates": ["2026-01-01", "2026-01-02", "2026-01-03"], "closes": [10, 11, 12]},
            "ETHUSD": {"dates": ["2026-01-02", "2026-01-03", "2026-01-04"], "closes": [20, 21, 22]},
        }
        dates, prices, symbols = align_common_history(series, ["BTCUSD", "ETHUSD"], min_observations=2)
        self.assertEqual(dates, ["2026-01-02", "2026-01-03"])
        self.assertEqual(symbols, ["BTCUSD", "ETHUSD"])
        np.testing.assert_allclose(prices, [[11, 20], [12, 21]])

    def test_rejects_short_common_history(self):
        series = {"BTCUSD": {"dates": ["2026-01-01"], "closes": [10]}}
        with self.assertRaises(ValueError):
            align_common_history(series, ["BTCUSD"], min_observations=120)

    def test_snapshot_fails_closed_without_validated_views(self):
        rng = np.random.default_rng(41)
        dates = [f"2026-01-{i:02d}" for i in range(1, 121)]
        series = {}
        for index, symbol in enumerate(("BTCUSD", "ETHUSD", "SOLUSD")):
            returns = rng.normal(0.0, 0.015, size=119)
            closes = (100.0 + index) * np.cumprod(np.r_[1.0, 1.0 + returns])
            series[symbol] = {"dates": dates, "closes": closes.tolist()}
        history = {
            "source": "test", "observed_at": "2026-04-30T00:00:00+00:00",
            "series": series, "market_caps": {"BTCUSD": 100, "ETHUSD": 50, "SOLUSD": 25},
        }
        result = build_portfolio_snapshot(
            history=history, symbols=list(series), min_history=120,
            min_train_samples=20, min_validation_samples=1000,
        )
        self.assertEqual(result["status"], "insufficient_eligible_assets")
        self.assertIsNone(result["portfolio"])


class CoinGeckoAdapterTests(unittest.TestCase):
    def test_asset_ids_are_explicit_and_unique(self):
        self.assertEqual(len(COINGECKO_IDS), 13)
        self.assertEqual(len(set(COINGECKO_IDS.values())), 13)
        self.assertEqual(COINGECKO_IDS["LEOUSD"], "leo-token")
        self.assertEqual(COINGECKO_IDS["ANVLUSD"], "anvil")

    def test_missing_api_key_fails_closed(self):
        client = CoinGeckoHistoryClient(api_key="")
        with self.assertRaisesRegex(RuntimeError, "COINGECKO_DEMO_API_KEY"):
            client.get_daily_prices("monero", days=365)


if __name__ == "__main__":
    unittest.main()
