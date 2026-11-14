import unittest

from market_data_worker.config import (
    PRODUCTION_SUPABASE_PROJECT_REF,
    STAGING_SUPABASE_PROJECT_REF,
    load_config,
    validate_staging_target,
)
from market_data_worker.providers.base import ProviderCapabilities, ProviderHealth


class WorkerConfigTests(unittest.TestCase):
    def valid_env(self):
        return {
            "MARKET_DATA_ENV": "staging",
            "SUPABASE_URL": f"https://{STAGING_SUPABASE_PROJECT_REF}.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-only-secret",
            "MARKET_DATA_ALLOWED_PROJECT_REF": STAGING_SUPABASE_PROJECT_REF,
        }

    def test_loads_staging_configuration(self):
        config = load_config(self.valid_env())
        self.assertEqual(config.environment, "staging")
        self.assertEqual(config.interval_seconds, 900)
        self.assertIsNone(config.eodhd_api_token)

    def test_rejects_production_environment(self):
        env = self.valid_env()
        env["MARKET_DATA_ENV"] = "production"
        with self.assertRaisesRegex(RuntimeError, "restricted to staging"):
            load_config(env)

    def test_rejects_production_project_ref(self):
        with self.assertRaisesRegex(RuntimeError, "approved staging"):
            validate_staging_target(
                environment="staging",
                supabase_url=f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co",
                allowed_project_ref=PRODUCTION_SUPABASE_PROJECT_REF,
            )

    def test_rejects_wrong_host(self):
        env = self.valid_env()
        env["SUPABASE_URL"] = f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co"
        with self.assertRaisesRegex(RuntimeError, "production or an unknown"):
            load_config(env)

    def test_requires_backend_secret(self):
        env = self.valid_env()
        env.pop("SUPABASE_SERVICE_ROLE_KEY")
        with self.assertRaisesRegex(RuntimeError, "SUPABASE_URL"):
            load_config(env)

    def test_rejects_too_fast_polling(self):
        env = self.valid_env()
        env["MARKET_DATA_INTERVAL_SECONDS"] = "10"
        with self.assertRaisesRegex(RuntimeError, "between 60 and 3600"):
            load_config(env)

    def test_rejects_non_integer_polling(self):
        env = self.valid_env()
        env["MARKET_DATA_INTERVAL_SECONDS"] = "fast"
        with self.assertRaisesRegex(RuntimeError, "must be an integer"):
            load_config(env)


class ProviderContractTests(unittest.TestCase):
    def test_capabilities_are_explicit_and_immutable(self):
        capabilities = ProviderCapabilities(
            asset_classes=frozenset({"crypto"}),
            quote_modes=frozenset({"last"}),
            intervals=frozenset({"1m", "1h"}),
            realtime=True,
            websocket=True,
        )
        self.assertIn("crypto", capabilities.asset_classes)
        self.assertTrue(capabilities.realtime)

    def test_health_is_structured(self):
        health = ProviderHealth(
            provider="binance",
            healthy=True,
            checked_at="2026-11-14T12:00:00+00:00",
            latency_ms=42.0,
        )
        self.assertTrue(health.healthy)
        self.assertEqual(health.provider, "binance")


if __name__ == "__main__":
    unittest.main()
