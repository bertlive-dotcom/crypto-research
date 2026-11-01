"""Configuration for the global, mixed-horizon opportunity engine.

These are discovery categories and seed symbols, not a claim that every
instrument is currently covered by a connected data provider.
"""

ASSET_CLASSES = ("equity", "etf", "index", "crypto", "forex", "commodity", "future")

DEFAULT_HORIZONS = {
    "short": {"label": "1-10 days", "min_days": 1, "max_days": 10},
    "medium": {"label": "2-12 weeks", "min_days": 14, "max_days": 84},
    "long": {"label": "3-24 months", "min_days": 90, "max_days": 730},
}

# Seed watchlists are starting points only. Discovery must expand them only
# after a provider confirms symbol, venue, currency and instrument coverage.
DEFAULT_UNIVERSE_SEEDS = {
    "equity": ["NVDA", "TSM", "ASML", "MSFT", "GOOGL", "AMZN", "AVGO", "SU.PA"],
    "etf": ["SPY", "QQQ", "VT", "IWDA", "EEM"],
    "index": ["SPX", "NDX", "SX5E", "HSI", "N225"],
    "crypto": ["BTC", "ETH", "SOL", "LINK", "XLM", "SUI", "HYPE"],
    "forex": ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF"],
    "commodity": ["XAU/USD", "XAG/USD", "WTI", "BRENT", "COPPER", "NATGAS"],
    "future": [],
}

# Higher scores always mean a more attractive setup. risk_control means
# risk quality: a higher value indicates lower or better-controlled risk.
DEFAULT_SCORE_WEIGHTS = {
    "technical": 0.35,
    "fundamental": 0.30,
    "catalyst": 0.15,
    "liquidity": 0.10,
    "risk_control": 0.10,
}
MIN_SCORE_COVERAGE = 0.60