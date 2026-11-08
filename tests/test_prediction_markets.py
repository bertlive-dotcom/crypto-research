import unittest

from prediction_markets.polymarket import PolymarketClient, PolymarketDataError
from prediction_markets.scoring import probability_divergence, classify_market_category


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.payload)


class PredictionMarketScoringTests(unittest.TestCase):
    def test_probability_gap_in_percentage_points(self):
        result = probability_divergence(0.62, 0.55, threshold_pp=5)
        self.assertEqual(result["gap_pp"], 7.0)
        self.assertEqual(result["direction"], "market_higher")
        self.assertTrue(result["material"])

    def test_missing_reference_does_not_create_signal(self):
        result = probability_divergence(0.62, None)
        self.assertFalse(result["available"])
        self.assertIsNone(result["gap_pp"])
        self.assertFalse(result["material"])

    def test_probability_bounds_are_validated(self):
        with self.assertRaises(ValueError):
            probability_divergence(1.2, 0.5)

    def test_threshold_must_be_non_negative(self):
        with self.assertRaises(ValueError):
            probability_divergence(0.5, 0.5, threshold_pp=-1)

    def test_category_classification(self):
        self.assertEqual(classify_market_category("Will Bitcoin exceed $100k?"), "crypto")
        self.assertEqual(classify_market_category("Will the Fed cut rates?"), "macro")
        self.assertEqual(classify_market_category("Will Team A win?"), "other")


class PolymarketAdapterTests(unittest.TestCase):
    def test_normalize_binary_market(self):
        raw = {
            "id": "123",
            "question": "Will Bitcoin exceed $100k?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.61", "0.39"]',
            "clobTokenIds": '["yes-token", "no-token"]',
            "volume24hr": "125000",
            "liquidityNum": "42000",
            "slug": "bitcoin-over-100k",
            "active": True,
            "closed": False,
        }
        row = PolymarketClient.normalize_market(raw)
        self.assertEqual(row["market_id"], "123")
        self.assertEqual(row["category"], "crypto")
        self.assertEqual(row["yes_probability"], 0.61)
        self.assertEqual(row["no_probability"], 0.39)
        self.assertEqual(row["volume_usd"], 125000.0)
        self.assertEqual(row["yes_token_id"], "yes-token")
        self.assertIn("bitcoin-over-100k", row["url"])

    def test_fetch_markets_uses_public_active_market_endpoint(self):
        session = FakeSession([{
            "id": "1",
            "question": "Will the Fed cut rates?",
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.7", "0.3"],
            "active": True,
            "closed": False,
        }])
        report = PolymarketClient(session=session).fetch_markets(limit=25)
        self.assertEqual(report["returned"], 1)
        self.assertEqual(report["markets"][0]["category"], "macro")
        self.assertEqual(session.calls[0]["params"]["active"], "true")
        self.assertEqual(session.calls[0]["params"]["closed"], "false")

    def test_other_categories_are_excluded_by_default(self):
        session = FakeSession([{
            "id": "1", "question": "Will Team A win?",
            "active": True, "closed": False,
        }])
        report = PolymarketClient(session=session).fetch_markets()
        self.assertEqual(report["returned"], 0)

    def test_unexpected_response_fails_closed(self):
        with self.assertRaises(PolymarketDataError):
            PolymarketClient(session=FakeSession({"markets": []})).fetch_markets()

    def test_limit_validation(self):
        with self.assertRaises(ValueError):
            PolymarketClient(session=FakeSession([])).fetch_markets(limit=501)


if __name__ == "__main__":
    unittest.main()
