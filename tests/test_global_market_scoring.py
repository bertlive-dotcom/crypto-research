import unittest
from datetime import datetime, timezone, timedelta
from global_markets.config import ASSET_CLASSES, DEFAULT_HORIZONS, DEFAULT_UNIVERSE_SEEDS
from global_markets.scoring import rank_candidate

class GlobalMarketConfigTests(unittest.TestCase):
    def test_global_asset_classes_and_horizons_are_present(self):
        self.assertEqual(set(ASSET_CLASSES), {"equity", "etf", "index", "crypto", "forex", "commodity", "future"})
        self.assertEqual(set(DEFAULT_HORIZONS), {"short", "medium", "long"})
        self.assertIn("crypto", DEFAULT_UNIVERSE_SEEDS)
        self.assertIn("equity", DEFAULT_UNIVERSE_SEEDS)

class CandidateScoringTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        self.candidate = {"asset_id": "NASDAQ:NVDA", "symbol": "NVDA", "asset_class": "equity",
                          "price": 200.0, "observed_at": self.now.isoformat(),
                          "scores": {"technical": 80, "fundamental": 90, "catalyst": 70,
                                     "liquidity": 95, "risk_control": 60}}

    def test_scores_candidate_and_normalizes_weights(self):
        result = rank_candidate(self.candidate, now=self.now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["coverage"], 1.0)
        self.assertAlmostEqual(result["score"], 80.5)

    def test_withholds_score_when_coverage_is_too_low(self):
        candidate = dict(self.candidate, scores={"technical": 90})
        result = rank_candidate(candidate, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["score"])
        self.assertIn("insufficient_score_coverage", result["reasons"])

    def test_missing_fundamental_data_can_be_scored_with_disclosed_coverage(self):
        candidate = dict(self.candidate, scores={"technical": 80, "catalyst": 70, "liquidity": 90, "risk_control": 80})
        result = rank_candidate(candidate, now=self.now)
        self.assertTrue(result["eligible"])
        self.assertLess(result["coverage"], 1.0)

    def test_rejects_stale_data_when_limit_is_set(self):
        candidate = dict(self.candidate, observed_at=(self.now - timedelta(hours=2)).isoformat())
        result = rank_candidate(candidate, max_age_seconds=3600, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("stale_market_data", result["reasons"])

    def test_rejects_invalid_price_and_asset_class(self):
        candidate = dict(self.candidate, price=0, asset_class="unknown")
        result = rank_candidate(candidate, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("invalid_price", result["reasons"])
        self.assertIn("unsupported_asset_class", result["reasons"])

    def test_invalid_weights_fail_fast(self):
        with self.assertRaises(ValueError):
            rank_candidate(self.candidate, weights={"technical": -1}, now=self.now)

if __name__ == "__main__":
    unittest.main()