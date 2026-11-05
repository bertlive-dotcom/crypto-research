"""Environment-backed configuration for Market Scanner v1."""
from __future__ import annotations
import os
from urllib.parse import urlparse

WATCHLIST = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "XLMUSDT", "SUIUSDT", "HYPEUSDT")
QUOTE_ASSET = "USDT"
SCAN_INTERVAL_SECONDS = int(os.getenv("SCANNER_INTERVAL_SECONDS", "300"))
TOP_UNIVERSE_SIZE = int(os.getenv("SCANNER_TOP_UNIVERSE_SIZE", "50"))
MAX_CANDIDATES = int(os.getenv("SCANNER_MAX_CANDIDATES", "50"))
MIN_QUOTE_VOLUME_USDT = float(os.getenv("SCANNER_MIN_QUOTE_VOLUME_USDT", "10000000"))
MIN_PRICE_USDT = float(os.getenv("SCANNER_MIN_PRICE_USDT", "0.000001"))
MIN_SCORE = float(os.getenv("SCANNER_MIN_SCORE", "65"))
AUTO_ENTRY_SCORE = float(os.getenv("SCANNER_AUTO_ENTRY_SCORE", "80"))
STOP_LOSS_PCT = float(os.getenv("SCANNER_STOP_LOSS_PCT", "3"))
TAKE_PROFIT_PCT = float(os.getenv("SCANNER_TAKE_PROFIT_PCT", "6"))
MAX_OPEN_POSITIONS = int(os.getenv("SCANNER_MAX_OPEN_POSITIONS", "3"))
MAX_DAILY_LOSS_USDT = float(os.getenv("SCANNER_MAX_DAILY_LOSS_USDT", "2.4"))
STARTING_CAPITAL_USD = float(os.getenv("SCANNER_STARTING_CAPITAL_USD", "80"))
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
HTTP_TIMEOUT_SECONDS = int(os.getenv("SCANNER_HTTP_TIMEOUT_SECONDS", "15"))
ALLOWED_SUPABASE_PROJECT_REF = os.getenv("SCANNER_ALLOWED_SUPABASE_PROJECT_REF", "").strip()


def validate_staging_target(url: str = SUPABASE_URL, allowed_ref: str = ALLOWED_SUPABASE_PROJECT_REF) -> None:
    """Fail closed unless the worker is explicitly pinned to its staging project."""
    host = urlparse(url).hostname or ""
    expected_host = f"{allowed_ref}.supabase.co" if allowed_ref else ""
    if not allowed_ref or host != expected_host:
        raise RuntimeError(
            "Scanner startup blocked: set SCANNER_ALLOWED_SUPABASE_PROJECT_REF and "
            "point SUPABASE_URL to that exact Supabase staging project."
        )
