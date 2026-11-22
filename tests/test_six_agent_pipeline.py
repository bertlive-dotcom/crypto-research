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

    def test_worker_uses_completed_5m_ohlc_for_intrabar_stop_loss(self):
        from trading_desk import Signal, paper_entry

        class MemoryStore:
            def __init__(self):
                self.state = new_portfolio(80)
                self.saved = None
            def acquire_lock(self, worker_id): return True
            def load_state(self): return self.state
            def save_cycle(self, state, run, candidates, signals):
                self.saved = {"state": state, "run": run, "signals": signals}
            def release_lock(self, worker_id): pass

        class FixedClient:
            def klines(self, symbol, interval, limit, start_time=None, end_time=None):
                self.request = (symbol, interval, limit, start_time, end_time)
                # Last item is the forming candle; the preceding completed
                # candle crosses the position stop intrabar and recovers.
                return [
                    [0, "100", "101", "80", "100", "10", 299999],
                    [300000, "100", "102", "99", "101", "10", 599999],
                ]

        store = MemoryStore()
        position = paper_entry(
            store.state,
            Signal(asset="BTC", market="major", price_usd=100,
                   volume_24h_usd=10_000_000, gain_1h_pct=1.0),
            stop_loss_pct=10, take_profit_pct=20,
        )
        # A stop at 90.27 is crossed by the completed candle's low (80).
        position["opened_at"] = "1970-01-01T00:00:00+00:00"
        client = FixedClient()
        scan_run = {"analysed_count": 0, "candidate_count": 0}
        with patch.object(worker, "scan_market", return_value=([], scan_run)):
            result = worker.run_once(store, client)

        self.assertEqual(client.request[:3], ("BTCUSDT", "5m", 1000))
        self.assertEqual(result["paper_exits"][0]["reason"], "stop_loss")
        self.assertEqual(store.saved["state"]["open_positions"], [])
        self.assertEqual(len(store.saved["state"]["closed_trades"]), 1)


    def test_worker_excludes_partial_candle_that_started_before_position_entry(self):
        from trading_desk import Signal, paper_entry

        class MemoryStore:
            def __init__(self):
                self.state = new_portfolio(80)
                self.saved = None
            def acquire_lock(self, worker_id): return True
            def load_state(self): return self.state
            def save_cycle(self, state, run, candidates, signals): self.saved = state
            def release_lock(self, worker_id): pass

        class EntryBoundaryClient:
            def __init__(self): self.requested_start = None
            def klines(self, symbol, interval, limit, start_time=None, end_time=None):
                self.requested_start = start_time
                # The first candle began before entry and breached the stop.
                # The next candle began after entry and did not breach it.
                rows = [
                    [0, "100", "101", "80", "100", "10", 299999],
                    [300000, "100", "102", "99", "101", "10", 599999],
                ]
                return [row for row in rows if row[0] >= start_time][:limit]

        store = MemoryStore()
        position = paper_entry(
            store.state,
            Signal(asset="BTC", market="major", price_usd=100,
                   volume_24h_usd=10_000_000, gain_1h_pct=1.0),
            stop_loss_pct=10, take_profit_pct=20,
        )
        # Entry occurs at 00:02:30, halfway through the first 5m candle.
        position["opened_at"] = "1970-01-01T00:02:30+00:00"
        client = EntryBoundaryClient()

        with patch.object(
            worker, "scan_market",
            return_value=([], {"analysed_count": 0, "candidate_count": 0}),
        ):
            result = worker.run_once(store, client)

        self.assertEqual(client.requested_start, 150000)
        self.assertEqual(result["paper_exits"], [])
        self.assertEqual(len(store.saved["open_positions"]), 1)
        self.assertEqual(
            store.saved["open_positions"][0]["last_processed_candle_close_time"],
            599999,
        )

    def test_worker_replays_all_missed_closed_candles_after_downtime(self):
        from trading_desk import Signal, paper_entry

        class MemoryStore:
            def __init__(self):
                self.state = new_portfolio(80)
                self.saved = None
            def acquire_lock(self, worker_id): return True
            def load_state(self): return self.state
            def save_cycle(self, state, run, candidates, signals): self.saved = state
            def release_lock(self, worker_id): pass

        class DowntimeClient:
            def __init__(self, candles): self.candles = candles; self.requests = []
            def klines(self, symbol, interval, limit, start_time=None, end_time=None):
                self.requests.append(start_time)
                return [row for row in self.candles if row[0] >= start_time][:limit]

        # 30 minutes, 2 hours and 24 hours of missed 5m bars.
        for missed_candles in (6, 24, 288):
            with self.subTest(missed_candles=missed_candles):
                store = MemoryStore()
                position = paper_entry(
                    store.state,
                    Signal(asset="BTC", market="major", price_usd=100,
                           volume_24h_usd=10_000_000, gain_1h_pct=1.0),
                    stop_loss_pct=10, take_profit_pct=20,
                )
                position["opened_at"] = "1970-01-01T00:00:00+00:00"
                rows = []
                for index in range(missed_candles):
                    low = "80" if index == missed_candles // 2 else "99"
                    rows.append([
                        index * 300000, "100", "102", low, "100", "1",
                        index * 300000 + 299999,
                    ])
                client = DowntimeClient(rows)
                with patch.object(worker, "scan_market", return_value=([], {"analysed_count": 0, "candidate_count": 0})):
                    result = worker.run_once(store, client)

                self.assertEqual(result["paper_exits"][0]["reason"], "stop_loss")
                self.assertEqual(len(store.saved["closed_trades"]), 1)
                self.assertEqual(client.requests, [0])

    def test_worker_paginates_more_than_one_thousand_missed_candles(self):
        from scanner.worker import _closed_klines_since

        class PagedClient:
            def __init__(self): self.calls = []
            def klines(self, symbol, interval, limit, start_time=None, end_time=None):
                self.calls.append(start_time)
                if len(self.calls) == 1:
                    return [[i * 300000, "1", "2", "1", "2", "1", i * 300000 + 299999] for i in range(1000)]
                return [[1000 * 300000, "1", "2", "1", "2", "1", 1000 * 300000 + 299999]]

        client = PagedClient()
        rows = _closed_klines_since(client, "BTCUSDT", 0, now_ms=2_000_000_000)
        self.assertEqual(len(rows), 1001)
        self.assertEqual(len(client.calls), 2)
        self.assertGreater(client.calls[1], client.calls[0])

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
