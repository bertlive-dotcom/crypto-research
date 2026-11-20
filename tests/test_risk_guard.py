import unittest
from datetime import datetime, timezone

from scanner.risk_guard import evaluate_risk_guard
from trading_desk import Signal, new_portfolio, paper_entry


class RiskGuardTests(unittest.TestCase):
    def test_new_portfolio_is_allowed_and_initializes_equity_markers(self):
        portfolio = new_portfolio(80)
        result = evaluate_risk_guard(portfolio, datetime(2026, 11, 20, 9, tzinfo=timezone.utc))
        self.assertTrue(result["can_open_new_positions"])
        self.assertEqual(result["high_water_equity_usd"], 80)
        self.assertEqual(result["day_start_equity_usd"], 80)

    def test_daily_loss_blocks_new_entries_and_latches_for_utc_day(self):
        portfolio = new_portfolio(80)
        now = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
        evaluate_risk_guard(portfolio, now)
        portfolio["cash"] = 78.39
        result = evaluate_risk_guard(portfolio, now)
        self.assertFalse(result["can_open_new_positions"])
        self.assertIn("Daily loss limit breached", result["blocked_reasons"][0])

        portfolio["cash"] = 80
        recovered = evaluate_risk_guard(portfolio, now)
        self.assertFalse(recovered["can_open_new_positions"])

    def test_daily_loss_latch_resets_on_next_utc_day(self):
        portfolio = new_portfolio(80)
        day_one = datetime(2026, 11, 20, 23, 59, tzinfo=timezone.utc)
        evaluate_risk_guard(portfolio, day_one)
        portfolio["cash"] = 78
        self.assertFalse(evaluate_risk_guard(portfolio, day_one)["can_open_new_positions"])
        next_day = datetime(2026, 11, 21, 0, 1, tzinfo=timezone.utc)
        self.assertTrue(evaluate_risk_guard(portfolio, next_day)["can_open_new_positions"])

    def test_trailing_drawdown_breach_is_permanent(self):
        portfolio = new_portfolio(80)
        portfolio["risk_guard"] = {
            "utc_day": "2026-11-20",
            "day_start_equity_usd": 90,
            "high_water_equity_usd": 90,
        }
        portfolio["cash"] = 85.19
        result = evaluate_risk_guard(portfolio, datetime(2026, 11, 20, 9, tzinfo=timezone.utc))
        self.assertFalse(result["can_open_new_positions"])
        self.assertTrue(portfolio["risk_guard"]["max_drawdown_breached"])

        portfolio["cash"] = 95
        recovered = evaluate_risk_guard(portfolio, datetime(2026, 11, 20, 10, tzinfo=timezone.utc))
        self.assertFalse(recovered["can_open_new_positions"])

    def test_high_water_mark_tracks_new_equity_high(self):
        portfolio = new_portfolio(80)
        now = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
        evaluate_risk_guard(portfolio, now)
        portfolio["cash"] = 84
        result = evaluate_risk_guard(portfolio, now)
        self.assertEqual(result["high_water_equity_usd"], 84)

    def test_aggregate_floating_loss_blocks_new_entries(self):
        portfolio = new_portfolio(80)
        signal = Signal(
            asset="BTC", market="major", price_usd=100,
            volume_24h_usd=2_000_000, gain_1h_pct=0,
        )
        position = paper_entry(portfolio, signal, stop_loss_pct=10)
        position["last_price_usd"] = position["entry_fill_price"] * 0.70
        result = evaluate_risk_guard(
            portfolio, datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
        )
        self.assertFalse(result["can_open_new_positions"])
        self.assertLess(result["floating_pnl_usd"], -1.60)
        self.assertTrue(any("floating-loss" in reason for reason in result["blocked_reasons"]))

    def test_initial_high_water_never_starts_below_starting_capital(self):
        portfolio = new_portfolio(80)
        portfolio["cash"] = 75
        result = evaluate_risk_guard(
            portfolio, datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
        )
        self.assertEqual(result["high_water_equity_usd"], 80)
        self.assertEqual(result["drawdown_usd"], 5)

    def test_floating_loss_threshold_is_reachable_with_three_open_positions(self):
        portfolio = new_portfolio(80)
        for asset in ("BTC", "ETH", "SOL"):
            signal = Signal(
                asset=asset, market="major", price_usd=100,
                volume_24h_usd=2_000_000, gain_1h_pct=0,
            )
            position = paper_entry(portfolio, signal, stop_loss_pct=3)
            position["last_price_usd"] = position["entry_fill_price"] * 0.975
        result = evaluate_risk_guard(
            portfolio, datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
        )
        self.assertFalse(result["can_open_new_positions"])
        self.assertAlmostEqual(result["floating_loss_limit_usd"], 0.40)
        self.assertLess(result["floating_pnl_usd"], -0.40)
        self.assertTrue(any("floating-loss" in reason for reason in result["blocked_reasons"]))


if __name__ == "__main__":
    unittest.main()
