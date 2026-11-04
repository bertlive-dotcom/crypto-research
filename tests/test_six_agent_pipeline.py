import unittest
from scanner.agents import AGENT_NAMES, run_agent_pipeline
from trading_desk import new_portfolio
from scanner.config import validate_staging_target


def candidate(symbol="BTCUSDT", score=85, eligible=True):
    return {
        "symbol": symbol,
        "base_asset": symbol[:-4],
        "price_usdt": 100.0,
        "quote_volume_24h": 20_000_000,
        "score": score,
        "auto_entry_eligible": eligible,
        "hard_checks_pass": eligible,
        "hard_gate_failures": [],
        "reasons": [],
        "features": {
            "1h": {
                "candle_close_time": 123456,
                "rsi14": 55.0,
                "macd_hist": 0.2,
                "volume_ratio": 1.5,
            },
            "4h": {},
            "1d": {},
        },
    }


class SixAgentPipelineTests(unittest.TestCase):
    def test_staging_target_accepts_only_the_explicit_staging_project(self):
        validate_staging_target(
            "https://jgxrtvqxjtoxmdrpltng.supabase.co",
            "jgxrtvqxjtoxmdrpltng",
        )

    def test_staging_target_rejects_production_or_missing_allowlist(self):
        with self.assertRaises(RuntimeError):
            validate_staging_target(
                "https://bcwiihozbjworhkbufyf.supabase.co",
                "jgxrtvqxjtoxmdrpltng",
            )
        with self.assertRaises(RuntimeError):
            validate_staging_target(
                "https://jgxrtvqxjtoxmdrpltng.supabase.co", ""
            )

    def test_pipeline_runs_six_stages_and_authorizes_paper_candidate(self):
        result = run_agent_pipeline([candidate()], new_portfolio(80), mode="paper")
        self.assertEqual(result["agents"], list(AGENT_NAMES))
        self.assertEqual(result["scouted_count"], 1)
        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual(result["risk_approved_count"], 1)
        self.assertEqual(result["authorized_count"], 1)
        self.assertEqual(len(result["approved_candidates"]), 1)
        self.assertTrue(any(row["agent"] == "LOGGER" for row in result["audit"]))

    def test_filter_rejects_candidate_that_does_not_pass_hard_gates(self):
        row = candidate(eligible=False)
        row["hard_gate_failures"] = ["Volum relatiu insuficient"]
        result = run_agent_pipeline([row], new_portfolio(80))
        self.assertEqual(result["filtered_count"], 0)
        self.assertEqual(result["authorized_count"], 0)
        self.assertFalse(result["approved_candidates"])

    def test_scout_rejects_missing_closed_candle_timestamp(self):
        row = candidate()
        row["features"]["1h"].pop("candle_close_time")
        result = run_agent_pipeline([row], new_portfolio(80))
        self.assertEqual(result["scouted_count"], 0)
        self.assertEqual(result["authorized_count"], 0)
        self.assertEqual(result["audit"][0]["agent"], "SCOUT")
        self.assertEqual(result["audit"][0]["status"], "REJECTED")

    def test_executor_fails_closed_outside_paper_mode(self):
        result = run_agent_pipeline([candidate()], new_portfolio(80), mode="live")
        self.assertEqual(result["risk_approved_count"], 1)
        self.assertEqual(result["authorized_count"], 0)
        self.assertFalse(result["approved_candidates"])
        executor = [row for row in result["audit"] if row["agent"] == "EXECUTOR"]
        self.assertEqual(executor[0]["status"], "BLOCKED_MODE")

    def test_risk_manager_respects_existing_open_position_limit(self):
        portfolio = new_portfolio(80)
        portfolio["open_positions"] = [
            {"asset": "ETH"}, {"asset": "SOL"}, {"asset": "LINK"}
        ]
        result = run_agent_pipeline([candidate()], portfolio)
        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual(result["risk_approved_count"], 0)
        self.assertEqual(result["authorized_count"], 0)

    def test_scout_rejects_non_positive_price(self):
        row = candidate()
        row["price_usdt"] = 0
        result = run_agent_pipeline([row], new_portfolio(80))
        self.assertEqual(result["scouted_count"], 0)


if __name__ == "__main__":
    unittest.main()
