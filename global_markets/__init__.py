"""Global multi-asset discovery, market-data and ranking primitives."""
from .config import ASSET_CLASSES, DEFAULT_HORIZONS, DEFAULT_UNIVERSE_SEEDS
from .crypto_feed import CryptoWatchlistFeed
from .market_analysis import analyze_candles, analyze_feed
from .scoring import rank_candidate

__all__ = [
    "ASSET_CLASSES",
    "DEFAULT_HORIZONS",
    "DEFAULT_UNIVERSE_SEEDS",
    "CryptoWatchlistFeed",
    "analyze_candles",
    "analyze_feed",
    "rank_candidate",
]
