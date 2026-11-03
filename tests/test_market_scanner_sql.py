"""Integration tests for the scanner SQL migration against real PostgreSQL.

The CI job runs these tests only against a disposable PostgreSQL service.
No Supabase project, production database, API key, or trading account is used.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.errors import InsufficientPrivilege, RaiseException


def connect():
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        autocommit=True,
    )


@unittest.skipUnless(os.environ.get("PGHOST"), "requires the disposable PostgreSQL service")
class ScannerSqlPersistenceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = connect()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        with self.conn.cursor() as cur:
            # Reset to the database owner for fixture cleanup; production-facing
            # assertions below explicitly assume service_role/anon/authenticated.
            cur.execute("RESET ROLE")
            cur.execute("DELETE FROM public.trading_signals")
            cur.execute("DELETE FROM public.market_candidates")
            cur.execute("DELETE FROM public.scanner_runs")
            cur.execute("DELETE FROM public.scanner_paper_state")
            cur.execute("DELETE FROM public.market_scanner_lock")

    def _as_owner(self, sql, params=()):
        """Create fixtures as the database owner, never by weakening service_role."""
        with self.conn.cursor() as cur:
            cur.execute("RESET ROLE")
            cur.execute(sql, params)
            return cur.fetchone() if cur.description is not None else None

    def _as_service(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute("SET ROLE service_role")
            cur.execute(sql, params)
            return cur.fetchone()

    def test_state_rpc_survives_new_database_connection(self):
        state = {
            "cash": 78.25,
            "open_positions": [],
            "daily_risk": {
                "date": "2026-11-03",
                "start_equity_usd": 80.0,
                "baseline_persisted": True,
            },
        }
        self._as_service(
            "SELECT public.save_market_scanner_state(%s::jsonb)",
            (json.dumps(state),),
        )

        # A genuinely new connection proves the state was committed in PostgreSQL,
        # rather than retained in a Python object or transaction-local cache.
        with connect() as fresh:
            with fresh.cursor() as cur:
                cur.execute("SET ROLE service_role")
                cur.execute("SELECT state FROM public.scanner_paper_state WHERE id = 'default'")
                self.assertEqual(cur.fetchone()[0], state)

    def test_cycle_rpc_persists_state_run_candidate_and_signal(self):
        now = datetime.now(timezone.utc).isoformat()
        state = {"cash": 79.0, "open_positions": [], "cycle_id": "integration-1"}
        run = {"status": "completed", "scanned_at": now, "analysed_count": 1}
        candidates = [{
            "symbol": "BTCUSDT",
            "score": 87,
            "eligible": True,
            "auto_entry_eligible": True,
            "price_usdt": 70000,
            "quote_volume_24h": 25000000,
            "change_24h_pct": 1.25,
            "features": {"1h": {"rsi14": 55}},
            "reasons": ["integration-test"],
            "scanned_at": now,
        }]
        signals = [{
            "signal_id": "integration-signal-1",
            "symbol": "BTCUSDT",
            "direction": "long",
            "score": 87,
            "status": "approved",
            "price_usdt": 70000,
            "stop_price": 67900,
            "take_profit_price": 74200,
            "created_at": now,
        }]
        self._as_service(
            """SELECT public.save_market_scanner_cycle(
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb
            )""",
            tuple(json.dumps(value) for value in (state, run, candidates, signals)),
        )
        self.assertEqual(
            self._as_service("SELECT state FROM public.scanner_paper_state WHERE id='default'")[0],
            state,
        )
        self.assertEqual(self._as_service("SELECT status FROM public.scanner_runs ORDER BY id DESC LIMIT 1")[0], "completed")
        self.assertEqual(self._as_service("SELECT symbol, score FROM public.market_candidates"), ("BTCUSDT", 87))
        self.assertEqual(self._as_service("SELECT signal_id, direction FROM public.trading_signals"), ("integration-signal-1", "long"))

    def test_cycle_rpc_is_idempotent_for_candidate_and_signal_keys(self):
        now = datetime.now(timezone.utc).isoformat()
        candidate = {
            "symbol": "ETHUSDT", "score": 82, "eligible": True,
            "auto_entry_eligible": True, "price_usdt": 3000,
            "quote_volume_24h": 12000000, "change_24h_pct": 0.5,
            "features": {}, "reasons": [], "scanned_at": now,
        }
        signal = {
            "signal_id": "stable-signal", "symbol": "ETHUSDT", "direction": "short",
            "score": 82, "status": "approved", "price_usdt": 3000,
            "stop_price": 3090, "take_profit_price": 2820, "created_at": now,
        }
        args = (json.dumps({"cash": 80}), json.dumps({"status": "completed"}),
                json.dumps([candidate]), json.dumps([signal]))
        for _ in range(2):
            self._as_service(
                "SELECT public.save_market_scanner_cycle(%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)",
                args,
            )
        self.assertEqual(self._as_service("SELECT count(*) FROM public.market_candidates")[0], 1)
        self.assertEqual(self._as_service("SELECT count(*) FROM public.trading_signals")[0], 1)

    def test_lock_enforces_single_owner_and_allows_release_and_reacquire(self):
        first = self._as_service(
            "SELECT public.acquire_market_scanner_lock(%s, %s)", ("worker-a", 240)
        )[0]
        second = self._as_service(
            "SELECT public.acquire_market_scanner_lock(%s, %s)", ("worker-b", 240)
        )[0]
        wrong_release = self._as_service(
            "SELECT public.release_market_scanner_lock(%s)", ("worker-b",)
        )[0]
        right_release = self._as_service(
            "SELECT public.release_market_scanner_lock(%s)", ("worker-a",)
        )[0]
        reacquire = self._as_service(
            "SELECT public.acquire_market_scanner_lock(%s, %s)", ("worker-b", 240)
        )[0]
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertFalse(wrong_release)
        self.assertTrue(right_release)
        self.assertTrue(reacquire)

    def test_expired_lock_can_be_taken_over(self):
        self._as_owner(
            "INSERT INTO public.market_scanner_lock(id, worker_id, lease_until) VALUES ('singleton','old-worker',now()-interval '1 second')"
        )
        self.assertTrue(self._as_service(
            "SELECT public.acquire_market_scanner_lock(%s, %s)", ("new-worker", 240)
        )[0])
        self.assertEqual(self._as_service("SELECT worker_id FROM public.market_scanner_lock")[0], "new-worker")

    def test_rpc_rejects_invalid_payloads_without_partial_writes(self):
        with self.assertRaises(RaiseException):
            self._as_service(
                "SELECT public.save_market_scanner_state(%s::jsonb)", (json.dumps([]),)
            )
        with self.assertRaises(RaiseException):
            self._as_service(
                """SELECT public.save_market_scanner_cycle(
                    %s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb
                )""",
                (json.dumps({"cash": 80}), json.dumps({"status": "bad"}),
                 json.dumps(["not-an-object"]), json.dumps([])),
            )
        self.assertEqual(self._as_service("SELECT count(*) FROM public.scanner_runs")[0], 0)
        self.assertEqual(self._as_service("SELECT count(*) FROM public.market_candidates")[0], 0)

    def test_cycle_rpc_removes_records_older_than_30_days(self):
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        self._as_owner(
            "INSERT INTO public.scanner_runs(status,payload,created_at) VALUES ('old','{}'::jsonb,%s::timestamptz)",
            (old,),
        )
        self._as_owner(
            """INSERT INTO public.market_candidates
            (symbol,score,eligible,auto_entry_eligible,price_usdt,quote_volume_24h,
             change_24h_pct,features,reasons,scanned_at)
            VALUES ('OLDUSDT',1,false,false,1,1,0,'{}'::jsonb,'[]'::jsonb,%s::timestamptz)""",
            (old,),
        )
        self._as_service(
            """SELECT public.save_market_scanner_cycle(
                %s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb
            )""",
            (json.dumps({"cash": 80}), json.dumps({"status": "completed"}),
             "[]", "[]"),
        )
        self.assertEqual(self._as_service("SELECT count(*) FROM public.scanner_runs WHERE status='old'")[0], 0)
        self.assertEqual(self._as_service("SELECT count(*) FROM public.market_candidates WHERE symbol='OLDUSDT'")[0], 0)

    def test_rls_is_enabled_and_unprivileged_roles_cannot_read_or_execute(self):
        rls = self._as_service(
            """SELECT bool_and(c.relrowsecurity)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public'
              AND c.relname = ANY(%s)""",
            (["scanner_paper_state", "scanner_runs", "market_candidates",
              "trading_signals", "market_scanner_lock"],),
        )[0]
        self.assertTrue(rls)

        for role in ("anon", "authenticated"):
            with self.conn.cursor() as cur:
                cur.execute(f"SET ROLE {role}")
                with self.assertRaises(InsufficientPrivilege):
                    cur.execute("SELECT * FROM public.scanner_paper_state")
                cur.execute("RESET ROLE")
                cur.execute(f"SET ROLE {role}")
                with self.assertRaises(InsufficientPrivilege):
                    cur.execute(
                        "SELECT public.save_market_scanner_state(%s::jsonb)",
                        (json.dumps({"cash": 80}),),
                    )
                cur.execute("RESET ROLE")


if __name__ == "__main__":
    unittest.main()
