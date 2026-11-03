import unittest
from unittest.mock import patch
from scanner.indicators import ema, rsi, volume_ratio
from scanner.market_scanner import apply_paper_rules, consecutive_loss_streak, daily_total_pnl, score_candidate, scan_market
from scanner.store import enrich_candidate_diagnostics
from trading_desk import new_portfolio, Signal, paper_entry, paper_exit, ensure_daily_equity_baseline

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

    def test_daily_loss_guard_includes_open_unrealized_pnl(self):
        portfolio = new_portfolio(200)
        ensure_daily_equity_baseline(portfolio)
        portfolio["cash"] = 99.9
        portfolio["open_positions"] = [{
            "asset": "BTC", "direction": "long", "notional_usd": 100.0,
            "quantity": 1.0, "entry_fee_usd": 0.1, "last_price_usd": 97.0,
        }]
        self.assertLessEqual(daily_total_pnl(portfolio), -2.4)
        self.assertEqual(apply_paper_rules([self.candidate("ETHUSDT")], portfolio), [])

    def test_daily_loss_guard_fails_closed_when_open_mark_is_missing(self):
        portfolio = new_portfolio(80)
        portfolio["open_positions"] = [{"asset": "BTC"}]
        self.assertEqual(daily_total_pnl(portfolio), float("-inf"))
        self.assertEqual(apply_paper_rules([self.candidate()], portfolio), [])

    def test_three_consecutive_losses_pause_new_entries(self):
        portfolio = new_portfolio(80)
        portfolio["closed_trades"] = [
            {"closed_at": "2026-11-01T10:00:00+00:00", "realized_pnl_usd": -1.0},
            {"closed_at": "2026-11-02T10:00:00+00:00", "realized_pnl_usd": -0.5},
            {"closed_at": "2026-11-03T10:00:00+00:00", "realized_pnl_usd": -0.2},
        ]
        self.assertEqual(consecutive_loss_streak(portfolio), 3)
        self.assertEqual(apply_paper_rules([self.candidate()], portfolio), [])

    def test_winning_trade_resets_consecutive_loss_streak(self):
        portfolio = new_portfolio(80)
        portfolio["closed_trades"] = [
            {"closed_at": "2026-11-01T10:00:00+00:00", "realized_pnl_usd": -1.0},
            {"closed_at": "2026-11-02T10:00:00+00:00", "realized_pnl_usd": -0.5},
            {"closed_at": "2026-11-03T10:00:00+00:00", "realized_pnl_usd": 0.2},
        ]
        self.assertEqual(consecutive_loss_streak(portfolio), 0)
        self.assertEqual(len(apply_paper_rules([self.candidate()], portfolio)), 1)


    def test_daily_equity_loss_gate_includes_open_position_unrealized_loss(self):
        portfolio = new_portfolio(80)
        ensure_daily_equity_baseline(portfolio)
        signal = Signal(asset="BTC", market="major", price_usd=100.0,
                        volume_24h_usd=20_000_000, gain_1h_pct=0)
        position = paper_entry(portfolio, signal, stop_loss_pct=10)
        position["last_price_usd"] = 50.0
        self.assertEqual(apply_paper_rules([self.candidate("ETHUSDT")], portfolio), [])
        self.assertEqual(len(portfolio["open_positions"]), 1)

    def test_daily_equity_loss_gate_counts_consecutive_realized_losses(self):
        portfolio = new_portfolio(80)
        ensure_daily_equity_baseline(portfolio)
        for index in range(6):
            signal = Signal(asset=f"LOSS{index}", market="major", price_usd=100.0,
                            volume_24h_usd=20_000_000, gain_1h_pct=0)
            position = paper_entry(portfolio, signal, stop_loss_pct=10)
            paper_exit(portfolio, position["asset"], position["stop_price"] * 0.99,
                       position_id=position["position_id"], reason="stop_loss")
        self.assertEqual(apply_paper_rules([self.candidate("ETHUSDT")], portfolio), [])


    def test_three_live_positions_still_count_after_partial_close(self):
        portfolio = new_portfolio(80)
        ensure_daily_equity_baseline(portfolio)
        positions = []
        for asset in ("BTC", "ETH", "SOL"):
            signal = Signal(asset=asset, market="major", price_usd=100.0,
                            volume_24h_usd=20_000_000, gain_1h_pct=0)
            positions.append(paper_entry(portfolio, signal, stop_loss_pct=10))
        self.assertEqual(len(portfolio["open_positions"]), 3)
        paper_exit(portfolio, "BTC", 105.0, position_id=positions[0]["position_id"], fraction=0.5)
        self.assertEqual(len(portfolio["open_positions"]), 3)
        self.assertEqual(apply_paper_rules([self.candidate("XRPUSDT")], portfolio), [])

if __name__ == "__main__":
    unittest.main()
