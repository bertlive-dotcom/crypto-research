import unittest
from datetime import datetime, timezone

from scanner.risk_guard import evaluate_risk_guard
from trading_desk import new_portfolio


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


if __name__ == "__main__":
    unittest.main()
