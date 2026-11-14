"""Fail-closed configuration for the independent market-data worker."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Mapping


STAGING_SUPABASE_PROJECT_REF = "jgxrtvqxjtoxmdrpltng"
PRODUCTION_SUPABASE_PROJECT_REF = "bcwiihozbjworhkbufyf"


@dataclass(frozen=True)
class WorkerConfig:
    environment: str
    supabase_url: str
    supabase_service_role_key: str
    allowed_project_ref: str
    interval_seconds: int
    eodhd_api_token: str | None = None
    twelve_data_api_key: str | None = None
    financialdata_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    coingecko_api_key: str | None = None


def validate_staging_target(
    *,
    environment: str,
    supabase_url: str,
    allowed_project_ref: str,
) -> None:
    """Reject all targets except the explicitly approved staging project."""
    host = urlparse(supabase_url).hostname or ""
    expected_host = f"{STAGING_SUPABASE_PROJECT_REF}.supabase.co"
    if environment.strip().lower() != "staging":
        raise RuntimeError("Market-data worker is restricted to staging in this phase.")
    if allowed_project_ref != STAGING_SUPABASE_PROJECT_REF:
        raise RuntimeError("Allowed Supabase project ref must match the approved staging project.")
    if allowed_project_ref == PRODUCTION_SUPABASE_PROJECT_REF or host != expected_host:
        raise RuntimeError("Market-data worker refuses the production or an unknown Supabase target.")


def load_config(environ: Mapping[str, str] | None = None) -> WorkerConfig:
    """Load secrets without logging them and validate the staging-only target."""
    env = os.environ if environ is None else environ
    environment = env.get("MARKET_DATA_ENV", "").strip().lower()
    supabase_url = env.get("SUPABASE_URL", "").strip().rstrip("/")
    service_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    allowed_ref = env.get("MARKET_DATA_ALLOWED_PROJECT_REF", "").strip()
    if not supabase_url or not service_key or not allowed_ref:
        raise RuntimeError(
            "Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and "
            "MARKET_DATA_ALLOWED_PROJECT_REF in the worker secret manager."
        )
    try:
        interval = int(env.get("MARKET_DATA_INTERVAL_SECONDS", "900"))
    except ValueError as exc:
        raise RuntimeError("MARKET_DATA_INTERVAL_SECONDS must be an integer.") from exc
    if interval < 60 or interval > 3600:
        raise RuntimeError("MARKET_DATA_INTERVAL_SECONDS must be between 60 and 3600.")
    validate_staging_target(
        environment=environment,
        supabase_url=supabase_url,
        allowed_project_ref=allowed_ref,
    )
    return WorkerConfig(
        environment=environment,
        supabase_url=supabase_url,
        supabase_service_role_key=service_key,
        allowed_project_ref=allowed_ref,
        interval_seconds=interval,
        eodhd_api_token=env.get("EODHD_API_TOKEN") or None,
        twelve_data_api_key=env.get("TWELVE_DATA_API_KEY") or None,
        financialdata_api_key=env.get("FINANCIALDATA_API_KEY") or None,
        alpha_vantage_api_key=env.get("ALPHA_VANTAGE_API_KEY") or None,
        coingecko_api_key=env.get("COINGECKO_API_KEY") or None,
    )
