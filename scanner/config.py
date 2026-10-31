"""Environment-backed configuration for Market Scanner v1."""
from __future__ import annotations
import os

WATCHLIST = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "XLMUSDT", "SUIUSDT", "HYPEUSDT")
QUOTE_ASSET = "USDT"
SCAN_INTERVAL_SECONDS = int(os.getenv("SCANNER_INTERVAL_SECONDS", "300"))
TOP_UNIVERSE_SIZE = int(os.getenv("SCANNER_TOP_UNIVERSE_SIZE", "30"))
MAX_CANDIDATES = int(os.getenv("SCANNER_MAX_CANDIDATES", "20"))
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
