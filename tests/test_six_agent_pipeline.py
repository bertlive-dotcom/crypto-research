import unittest
from unittest.mock import patch
from scanner.agents import AGENT_NAMES, run_agent_pipeline
from trading_desk import new_portfolio
from scanner.config import validate_staging_target
from scanner.market_scanner import _features
from scanner.store import ScannerStore
from scanner import worker


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
                "change_pct": 2.0,
            },
            "4h": {},
            "1d": {},
        },
    }


class SupabaseScannerAuthTests(unittest.TestCase):
    def test_new_secret_key_uses_apikey_without_bearer(self):
        store = ScannerStore(
            url="https://jgxrtvqxjtoxmdrpltng.supabase.co",
            key="sb_secret_test_placeholder",
        )
        self.assertEqual(store.headers["apikey"], "sb_secret_test_placeholder")
        self.assertNotIn("Authorization", store.headers)

    def test_legacy_service_role_jwt_uses_apikey_and_bearer(self):
        token = "eyJ_test_legacy_service_role"
        store = ScannerStore(
            url="https://jgxrtvqxjtoxmdrpltng.supabase.co", key=token
        )
        self.assertEqual(store.headers["apikey"], token)
        self.assertEqual(store.headers["Authorization"], "Bearer " + token)

    def test_publishable_key_is_rejected_for_worker(self):
        with self.assertRaisesRegex(ValueError, "not a publishable key"):
            ScannerStore(
                url="https://jgxrtvqxjtoxmdrpltng.supabase.co",
                key="sb_publishable_test_placeholder",
            )


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

    def test_empty_filter_records_remaining_stages_as_skipped(self):
        row = candidate(eligible=False)
        row["hard_gate_failures"] = ["Trend confirmation missing"]
        result = run_agent_pipeline([row], new_portfolio(80))
        statuses = {
            item["agent"]: item["status"]
            for item in result["audit"]
            if item["symbol"] == "*"
        }
        self.assertEqual(statuses["ANALYST"], "SKIPPED")
        self.assertEqual(statuses["RISK_MANAGER"], "SKIPPED")
        self.assertEqual(statuses["EXECUTOR"], "SKIPPED")
        self.assertEqual(statuses["LOGGER"], "RECORDED")
        self.assertEqual(result["authorized_count"], 0)

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


class PaperCycleIntegrationTests(unittest.TestCase):
    def test_features_calculate_change_from_closed_candles(self):
        closes = [100.0] * 60 + [102.0]
        raw = [
            [index, close, close + 1, close - 1, close, 100.0]
            for index, close in enumerate(closes)
        ]
        # This still-forming candle must not affect the computed return.
        raw.append([61, 102.0, 1100.0, 1.0, 1000.0, 1000.0])

        result = _features(raw)

        self.assertAlmostEqual(result["change_pct"], 2.0)
        self.assertEqual(result["close"], 102.0)

    def test_worker_opens_and_persists_a_mocked_paper_entry(self):
        class MemoryStore:
            def __init__(self):
                self.state = new_portfolio(80)
                self.saved = None
                self.locked = False

            def acquire_lock(self, worker_id):
                self.locked = True
                return True

            def load_state(self):
                return self.state

            def save_cycle(self, state, run, candidates, signals):
                self.saved = {"state": state, "run": run, "candidates": candidates, "signals": signals}

            def release_lock(self, worker_id):
                self.locked = False

        class FixedClient:
            def prices(self):
                return {}

        store = MemoryStore()
        scan_run = {"analysed_count": 1, "candidate_count": 1}
        with patch.object(worker, "scan_market", return_value=([candidate()], scan_run)):
            result = worker.run_once(store, FixedClient())

        self.assertEqual(result["agent_pipeline"]["authorized_count"], 1)
        self.assertEqual(result["paper_entries"], 1)
        self.assertEqual(len(store.saved["signals"]), 1)
        self.assertEqual(len(store.saved["state"]["open_positions"]), 1)
        self.assertFalse(store.locked)


if __name__ == "__main__":
    unittest.main()
