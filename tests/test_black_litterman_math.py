"""Deterministic mathematical tests for the independent BL analytics layer."""
import unittest
import numpy as np
from portfolio_engine.analytics import (
    estimate_covariance, market_cap_weights, market_equilibrium_returns,
    posterior_expected_returns, simple_returns,
)


class ReturnsTests(unittest.TestCase):
    def test_simple_returns_exact(self):
        prices = np.array([[100.0, 200.0], [110.0, 180.0], [121.0, 198.0]])
        np.testing.assert_allclose(simple_returns(prices), [[0.10, -0.10], [0.10, 0.10]])

    def test_period_returns(self):
        np.testing.assert_allclose(simple_returns([100, 110, 121], periods=2), [0.21])

    def test_rejects_non_positive_or_non_finite_prices(self):
        for prices in ([1.0, 0.0], [1.0, np.nan], [1.0, np.inf]):
            with self.subTest(prices=prices), self.assertRaises(ValueError):
                simple_returns(prices)

    def test_rejects_invalid_periods(self):
        with self.assertRaises(ValueError):
            simple_returns([1.0, 2.0], periods=0)


class CovarianceTests(unittest.TestCase):
    def test_shrinkage_reduces_off_diagonal_covariance(self):
        returns = np.array([[0.01, 0.02], [0.02, 0.04], [-0.01, -0.02],
                            [0.03, 0.06], [-0.02, -0.04]])
        raw = estimate_covariance(returns, shrinkage=0.0)
        shrunk = estimate_covariance(returns, shrinkage=0.25)
        self.assertAlmostEqual(shrunk[0, 1], raw[0, 1] * 0.75, places=14)

    def test_covariance_is_symmetric_positive_definite(self):
        returns = np.random.default_rng(7).normal(0.0, 0.02, size=(80, 4))
        covariance = estimate_covariance(returns)
        np.testing.assert_allclose(covariance, covariance.T, atol=1e-14)
        self.assertGreater(np.linalg.eigvalsh(covariance).min(), 0.0)

    def test_annualization_scales_covariance(self):
        returns = np.random.default_rng(9).normal(0.0, 0.01, size=(30, 2))
        daily = estimate_covariance(returns, annualization=1)
        weekly = estimate_covariance(returns, annualization=7)
        np.testing.assert_allclose(weekly, daily * 7.0, rtol=1e-10, atol=1e-14)

    def test_single_asset_shape(self):
        covariance = estimate_covariance([0.01, -0.02, 0.03])
        self.assertEqual(covariance.shape, (1, 1))
        self.assertGreater(covariance[0, 0], 0.0)

    def test_rejects_invalid_returns(self):
        with self.assertRaises(ValueError):
            estimate_covariance([[0.1, np.nan], [0.2, 0.3]])


class EquilibriumTests(unittest.TestCase):
    def test_market_caps_are_aligned_and_normalized(self):
        weights = market_cap_weights({"ETH": 200.0, "BTC": 800.0}, ["BTC", "ETH"])
        np.testing.assert_allclose(weights, [0.8, 0.2])

    def test_missing_market_cap_fails_closed(self):
        with self.assertRaises(ValueError):
            market_cap_weights({"BTC": 100.0}, ["BTC", "ETH"])

    def test_non_positive_market_cap_is_rejected(self):
        with self.assertRaises(ValueError):
            market_cap_weights([100.0, 0.0])

    def test_implied_equilibrium_returns(self):
        sigma = np.array([[0.04, 0.01], [0.01, 0.09]])
        weights = np.array([0.75, 0.25])
        expected = 2.0 * sigma @ weights
        np.testing.assert_allclose(market_equilibrium_returns(sigma, weights, 2.0), expected)

    def test_weights_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            market_equilibrium_returns(np.eye(2), [0.4, 0.4])


class BlackLittermanTests(unittest.TestCase):
    def test_no_views_returns_prior_unchanged(self):
        prior = np.array([0.02, 0.04])
        posterior = posterior_expected_returns(
            np.eye(2), prior, np.empty((0, 2)), np.empty(0), np.empty((0, 0))
        )
        np.testing.assert_allclose(posterior, prior)

    def test_relative_view_moves_posterior_in_expected_direction(self):
        sigma = np.diag([0.04, 0.09])
        prior = np.array([0.01, 0.01])
        p = np.array([[1.0, -1.0]])
        q = np.array([0.08])
        omega = np.array([[0.002]])
        posterior = posterior_expected_returns(sigma, prior, p, q, omega, tau=0.05)
        self.assertGreater(posterior[0] - posterior[1], 0.0)
        self.assertGreater(posterior[0], prior[0])
        self.assertLess(posterior[1], prior[1])

    def test_rejects_non_positive_definite_covariance(self):
        with self.assertRaises(ValueError):
            posterior_expected_returns(
                [[1.0, 2.0], [2.0, 1.0]], [0.0, 0.0],
                [[1.0, 0.0]], [0.1], [[0.01]],
            )

    def test_rejects_inconsistent_view_dimensions(self):
        with self.assertRaises(ValueError):
            posterior_expected_returns(
                np.eye(2), [0.0, 0.0], [[1.0, 0.0]], [0.1, 0.2], [[0.01]]
            )


if __name__ == "__main__":
    unittest.main()
