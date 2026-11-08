import unittest
from unittest.mock import patch
from scanner.indicators import ema, rsi, volume_ratio
from scanner.market_scanner import _features, apply_paper_rules, score_candidate, scan_market
from scanner.store import enrich_candidate_diagnostics
from trading_desk import new_portfolio

class IndicatorTests(unittest.TestCase):
    def test_ema_requires_enough_values(self):
        self.assertEqual(ema([1, 2], 3), [])
        self.assertEqual(ema([1, 2, 3], 3), [2.0])

    def test_rsi_rising_series_is_100(self):
        self.assertEqual(rsi(list(range(1, 20))), 100.0)

    def test_volume_ratio_uses_previous_baseline(self):
        self.assertAlmostEqual(volume_ratio([10] * 20 + [20]), 2.0)

class ScannerRuleTests(unittest.TestCase):
    def test_newly_listed_daily_pair_can_use_ema20_before_ema50_warmup(self):
        # 45 closed daily candles plus one forming candle: realistic for HYPE
        # shortly after its Binance Spot listing.
        raw = []
        for i in range(46):
            price = 100.0 + i
            raw.append([i, str(price), str(price + 1), str(price - 1),
                        str(price), "1000"])
        features = _features(raw, min_closed_candles=20)
        self.assertIsNotNone(features["ema20"])
        self.assertIsNone(features["ema50"])
        self.assertEqual(features["close"], 144.0)

    def test_one_hour_still_requires_full_ema50_history(self):
        raw = []
        for i in range(60):
            price = 100.0 + i
            raw.append([i, str(price), str(price + 1), str(price - 1),
                        str(price), "1000"])
        with self.assertRaisesRegex(ValueError, "received 59, need 60"):
            _features(raw)

    def test_score_80_can_pass_when_hard_gates_pass(self):
        ticker = {"symbol": "BTCUSDT", "base_asset": "BTC", "price_usdt": 102.0,
                  "quote_volume_24h": 20_000_000, "change_24h_pct": 1.0}
        one_hour = {"close": 101.0, "ema20": 100.0, "ema50": 95.0,
                    "rsi14": 40.0, "macd_hist": -0.1, "atr_pct": 2.0,
                    "volume_ratio": 1.5, "candle_close_time": 123}
        four_hour = {"close": 110.0, "ema20": 100.0}
        daily = {"close": 120.0, "ema20": 100.0}
        result = score_candidate(ticker, one_hour, four_hour, daily)
        self.assertGreaterEqual(result["score"], 80)
        self.assertTrue(result["hard_checks_pass"])
        self.assertTrue(result["auto_entry_eligible"])
        self.assertEqual(result["entry_status"], "READY")
        self.assertEqual(result["score_gap_to_auto_entry"], 0)
        self.assertIn("MACD 1h no positiu", result["quality_warnings"])
        self.assertIn("RSI 1h fora del rang preferit 48-70", result["quality_warnings"])

    def test_score_does_not_override_failed_hard_gate(self):
        ticker = {"symbol": "BTCUSDT", "base_asset": "BTC", "price_usdt": 106.0,
                  "quote_volume_24h": 20_000_000, "change_24h_pct": 1.0}
        one_hour = {"close": 101.0, "ema20": 100.0, "ema50": 95.0,
                    "rsi14": 50.0, "macd_hist": 0.1, "atr_pct": 2.0,
                    "volume_ratio": 1.5, "candle_close_time": 123}
        four_hour = {"close": 110.0, "ema20": 100.0}
        daily = {"close": 120.0, "ema20": 100.0}
        result = score_candidate(ticker, one_hour, four_hour, daily)
        self.assertGreaterEqual(result["score"], 80)
        self.assertFalse(result["hard_checks_pass"])
        self.assertFalse(result["auto_entry_eligible"])
        self.assertEqual(result["entry_status"], "WATCH")
        self.assertIn("Preu més d'un 4% sobre EMA20 1h", result["hard_gate_failures"])

    def candidate(self, symbol="BTCUSDT", score=85):
        features = {
            "1h": {"candle_close_time": 123456},
            "4h": {}, "1d": {},
        }
        return {
            "symbol": symbol, "base_asset": symbol[:-4], "price_usdt": 100.0,
            "quote_volume_24h": 20_000_000, "score": score,
            "auto_entry_eligible": score >= 80, "features": features, "reasons": [],
        }


    def test_legacy_candidate_rebuilds_diagnostics_from_saved_features(self):
        row = {
            "symbol": "SPCXBUSDT", "base_asset": "SPCXB", "price_usdt": 102.0,
            "score": 70, "eligible": True, "auto_entry_eligible": False,
            "features": {
                "1h": {"close": 101.0, "ema20": 100.0, "ema50": 95.0,
                       "rsi14": 50.0, "macd_hist": -0.1, "atr_pct": 2.0,
                       "volume_ratio": 0.8, "candle_close_time": 123},
                "4h": {"close": 110.0, "ema20": 100.0},
                "1d": {"close": 120.0, "ema20": 100.0},
            },
            "reasons": ["1h relative volume below 1.2x"],
        }
        result = enrich_candidate_diagnostics(row)
        self.assertEqual(result["entry_status"], "WATCH")
        self.assertEqual(result["score_gap_to_auto_entry"], 10)
        self.assertIn("Volum relatiu 1h inferior a 1,2x", result["hard_gate_failures"])
        self.assertEqual(result["quality_warnings"], ["MACD 1h no positiu"])
        self.assertFalse(result["auto_entry_eligible"])

    def test_legacy_candidate_without_features_is_marked_incomplete(self):
        result = enrich_candidate_diagnostics({"symbol": "OLDUSDT", "score": 50})
        self.assertEqual(result["entry_status"], "LEGACY_UNAVAILABLE")
        self.assertIsNone(result["hard_gate_failures"])

    def test_scan_market_assigns_one_timestamp_to_entire_cycle(self):
        class FakeClient:
            def universe(self):
                return [
                    {"symbol": f"COIN{i}USDT", "base_asset": f"COIN{i}",
                     "price_usdt": 100.0, "quote_volume_24h": 20_000_000,
                     "change_24h_pct": 1.0}
                    for i in range(3)
                ]

            def klines(self, symbol, interval, limit):
                return []

        features = {
            "close": 101.0, "ema20": 100.0, "ema50": 95.0,
            "rsi14": 55.0, "macd_hist": 0.2, "atr_pct": 2.0,
            "volume_ratio": 1.5, "candle_close_time": 123456,
        }
        with patch("scanner.market_scanner._features", return_value=features):
            candidates, run = scan_market(FakeClient())

        self.assertEqual(len(candidates), 3)
        timestamps = {row["scanned_at"] for row in candidates}
        self.assertEqual(len(timestamps), 1)
        self.assertEqual(run["scanned_at"], next(iter(timestamps)))

    def test_auto_entry_requires_strong_score(self):
        portfolio = new_portfolio(80)
        approved = apply_paper_rules([self.candidate(score=79)], portfolio)
        self.assertEqual(approved, [])

    def test_open_asset_is_not_reentered(self):
        portfolio = new_portfolio(80)
        portfolio["open_positions"].append({"asset": "BTC"})
        approved = apply_paper_rules([self.candidate()], portfolio)
        self.assertEqual(approved, [])

    def test_max_open_positions_blocks_new_entry(self):
        portfolio = new_portfolio(80)
        portfolio["open_positions"] = [{"asset": f"A{i}"} for i in range(3)]
        self.assertEqual(apply_paper_rules([self.candidate()], portfolio), [])

if __name__ == "__main__":
    unittest.main()
