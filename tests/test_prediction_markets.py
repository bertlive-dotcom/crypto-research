import unittest

from prediction_markets.polymarket import PolymarketClient, PolymarketDataError
from prediction_markets.scoring import (
    probability_divergence,
    classify_market_category,
    calibration_metrics,
)


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
    def __init__(self, payloads):
        self.payloads = list(payloads) if (
            isinstance(payloads, list) and payloads and isinstance(payloads[0], list)
        ) else [payloads]
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        payload = self.payloads.pop(0) if self.payloads else []
        return FakeResponse(payload)


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

    def test_word_boundaries_prevent_ether_false_positive_in_whether(self):
        self.assertEqual(
            classify_market_category("Will the Bank of Russia decide whether to cut rates?", ["macro"]),
            "macro",
        )

    def test_calibration_metrics(self):
        result = calibration_metrics([0.8, 0.2, 0.6], [1, 0, 0])
        self.assertEqual(result["sample_size"], 3)
        self.assertAlmostEqual(result["brier_score"], 0.146667, places=6)
        self.assertAlmostEqual(result["observed_frequency"], 0.333333, places=6)

    def test_calibration_empty_sample_is_unavailable(self):
        result = calibration_metrics([], [])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["brier_score"])

    def test_calibration_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            calibration_metrics([0.2], [2])
        with self.assertRaises(ValueError):
            calibration_metrics([0.2, 0.3], [1])


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

    def test_fetch_markets_uses_tagged_event_endpoints(self):
        crypto = [{
            "id": "event-crypto",
            "title": "What price will Bitcoin hit?",
            "slug": "bitcoin-price-event",
            "markets": [{
                "id": "1",
                "question": "Will Bitcoin exceed $100k?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.7", "0.3"]',
                "volume24hr": "5000",
                "active": True,
                "closed": False,
            }],
        }]
        macro = [{
            "id": "event-macro",
            "title": "Federal Reserve decision",
            "slug": "fed-decision",
            "markets": [{
                "id": "2",
                "question": "Will rates be cut?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.4", "0.6"]',
                "active": True,
                "closed": False,
            }],
        }]
        session = FakeSession([crypto, macro])
        report = PolymarketClient(session=session).fetch_markets(limit=25)
        self.assertEqual(report["returned"], 2)
        by_id = {row["market_id"]: row for row in report["markets"]}
        self.assertEqual(by_id["1"]["category"], "crypto")
        self.assertEqual(by_id["2"]["category"], "macro")
        self.assertEqual(session.calls[0]["url"], "https://gamma-api.polymarket.com/events")
        self.assertEqual(session.calls[0]["params"]["tag_slug"], "crypto")
        self.assertEqual(session.calls[1]["params"]["tag_slug"], "macro")
        self.assertIn("bitcoin-price-event", by_id["1"]["url"])

    def test_other_categories_are_excluded(self):
        other = [{
            "id": "event-other",
            "title": "Basketball",
            "markets": [{
                "id": "3", "question": "Will Team A win?",
                "active": True, "closed": False,
            }],
        }]
        session = FakeSession([other, []])
        report = PolymarketClient(session=session).fetch_markets()
        self.assertEqual(report["returned"], 0)

    def test_unexpected_response_fails_closed(self):
        with self.assertRaises(PolymarketDataError):
            PolymarketClient(session=FakeSession({"events": []})).fetch_markets()

    def test_limit_validation(self):
        with self.assertRaises(ValueError):
            PolymarketClient(session=FakeSession([[], []])).fetch_markets(limit=501)


if __name__ == "__main__":
    unittest.main()
