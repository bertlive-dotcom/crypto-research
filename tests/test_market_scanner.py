import unittest
from scanner.indicators import ema, rsi, volume_ratio
from scanner.market_scanner import apply_paper_rules, score_candidate
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
    def test_score_80_can_pass_when_hard_gates_pass(self):
        ticker = {"symbol": "BTCUSDT", "base_asset": "BTC", "price_usdt": 102.0,
                  "quote_volume_24h": 20_000_000, "change_24h_pct": 1.0}
        one_hour = {"close": 101.0, "ema20": 100.0, "ema50": 95.0,
                    "rsi14": 40.0, "macd_hist": -0.1, "atr_pct": 2.0,
                    "volume_ratio": 1.5, "candle_close_time": 123}
        four_hour = {"close": 110.0, "ema20": 100.0}
        daily = {"close": 120.0, "ema20": 100.0}
        result = score_candidate(ticker, one_hour, four_hour, daily)
        self.assertEqual(result["score"], 80)
        self.assertTrue(result["hard_checks_pass"])
        self.assertTrue(result["auto_entry_eligible"])

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
