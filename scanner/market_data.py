"""Public Binance Spot market-data client. No authenticated endpoints are used."""
from __future__ import annotations
import requests
from .config import BINANCE_BASE_URL, HTTP_TIMEOUT_SECONDS, MIN_QUOTE_VOLUME_USDT, MIN_PRICE_USDT, QUOTE_ASSET, TOP_UNIVERSE_SIZE, WATCHLIST

class BinanceDataError(RuntimeError):
    pass

class BinanceSpotClient:
    def __init__(self, base_url: str = BINANCE_BASE_URL, timeout: int = HTTP_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "crypto-research-market-scanner/1.0"})

    def _get(self, path: str, params=None):
        try:
            response = self.session.get(self.base_url + path, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BinanceDataError(f"Binance request failed for {path}: {exc}") from exc
        if isinstance(payload, dict) and payload.get("code") is not None:
            raise BinanceDataError(f"Binance API error: {payload.get('msg', payload)}")
        return payload

    def exchange_symbols(self) -> set[str]:
        data = self._get("/api/v3/exchangeInfo")
        return {
            item["symbol"] for item in data.get("symbols", [])
            if item.get("status") == "TRADING"
            and item.get("isSpotTradingAllowed", True)
            and item.get("quoteAsset") == QUOTE_ASSET
            and item.get("quoteOrderQtyMarketAllowed", True)
        }

    def universe(self) -> list[dict]:
        tradable = self.exchange_symbols()
        tickers = self._get("/api/v3/ticker/24hr")
        rows = []
        for row in tickers:
            symbol = row.get("symbol", "")
            if symbol not in tradable:
                continue
            base = symbol[:-len(QUOTE_ASSET)]
            # Avoid stablecoin pairs and leveraged-token products.
            if base in {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "USDD", "BUSD"}:
                continue
            if any(base.endswith(tag) for tag in ("UP", "DOWN", "BULL", "BEAR")):
                continue
            try:
                price = float(row["lastPrice"])
                quote_volume = float(row["quoteVolume"])
                change = float(row["priceChangePercent"])
            except (KeyError, TypeError, ValueError):
                continue
            if price < MIN_PRICE_USDT or quote_volume < MIN_QUOTE_VOLUME_USDT:
                continue
            rows.append({
                "symbol": symbol, "base_asset": base, "quote_asset": QUOTE_ASSET,
                "price_usdt": price, "quote_volume_24h": quote_volume,
                "change_24h_pct": change, "source": "Binance Spot",
            })
        rows.sort(key=lambda x: x["quote_volume_24h"], reverse=True)
        selected = rows[:TOP_UNIVERSE_SIZE]
        by_symbol = {row["symbol"]: row for row in rows}
        for symbol in WATCHLIST:
            if symbol in by_symbol and symbol not in {x["symbol"] for x in selected}:
                selected.append(by_symbol[symbol])
        return selected

    def klines(self, symbol: str, interval: str, limit: int = 120) -> list[list]:
        return self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
