import re
import unittest
from pathlib import Path


class MarketScannerMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (
            Path(__file__).resolve().parents[1]
            / "supabase"
            / "market_scanner_v1.sql"
        ).read_text(encoding="utf-8")

    def function_body(self, name):
        match = re.search(
            rf"create or replace function public\.{name}\b.*?as \$\$(.*?)\$\$;",
            self.sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(match, f"Missing function definition: {name}")
        return match.group(1).lower()

    def test_table_privileges_revoke_public_and_api_roles(self):
        self.assertRegex(
            self.sql,
            r"revoke all on public\.scanner_paper_state.*?"
            r"from public, anon, authenticated;",
        )

    def test_lock_functions_reject_empty_worker_ids(self):
        for name in ("acquire_market_scanner_lock", "release_market_scanner_lock"):
            body = self.function_body(name)
            self.assertIn("p_worker_id is null", body)
            self.assertIn("btrim(p_worker_id) = ''", body)

    def test_save_cycle_validates_json_roots_and_array_items(self):
        body = self.function_body("save_market_scanner_cycle")
        for fragment in (
            "jsonb_typeof(p_state) <> 'object'",
            "jsonb_typeof(p_run) <> 'object'",
            "jsonb_typeof(p_candidates) <> 'array'",
            "jsonb_typeof(p_signals) <> 'array'",
            "each candidate must be a json object",
            "each signal must be a json object",
        ):
            self.assertIn(fragment, body)

    def test_rpc_execution_is_restricted_to_service_role(self):
        for signature in (
            "acquire_market_scanner_lock(text, integer)",
            "release_market_scanner_lock(text)",
            "save_market_scanner_state(jsonb)",
            "save_market_scanner_cycle(jsonb, jsonb, jsonb, jsonb)",
        ):
            self.assertRegex(
                self.sql,
                rf"revoke all on function public\.{re.escape(signature)} "
                r"from public, anon, authenticated;",
            )
            self.assertRegex(
                self.sql,
                rf"grant execute on function public\.{re.escape(signature)} "
                r"to service_role;",
            )


if __name__ == "__main__":
    unittest.main()
