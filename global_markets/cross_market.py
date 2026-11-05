"""Read-only BTC / S&P 500 / Nasdaq cross-market risk monitor.

The module uses closed 15-minute candles only. It is descriptive research:
it never emits trade orders or modifies either paper portfolio.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import requests

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
INTERVAL = "15min"


class CrossMarketDataError(RuntimeError):
    """Sanitized cross-market provider or data-quality error."""


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("candle timestamp is missing")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_twelve_data(payload: Any, symbol: str) -> list[dict[str, Any]]:
    """Normalize Twelve Data 15-minute bars; API request must specify UTC."""
    if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
        message = payload.get("message") if isinstance(payload, dict) else None
        raise CrossMarketDataError(str(message or "Twelve Data returned an unexpected time-series response"))
    rows = []
    seen = set()
    for item in payload["values"]:
        if not isinstance(item, dict):
            continue
        try:
            timestamp = _parse_utc(item.get("datetime"))
            close = float(item["close"])
            if not math.isfinite(close) or close <= 0 or timestamp in seen:
                continue
            seen.add(timestamp)
            rows.append({
                "symbol": symbol,
                "timestamp": timestamp.isoformat(),
                "close_timestamp": (timestamp + timedelta(minutes=15)).isoformat(),
                "close": close,
                "source": "twelve_data",
                "interval": INTERVAL,
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    rows.sort(key=lambda row: row["timestamp"])
    if not rows:
        raise CrossMarketDataError("Twelve Data returned no valid 15-minute candles")
    return rows


class TwelveDataIntradayClient:
    def __init__(self, api_key: str, *, session: requests.Session | None = None, timeout: float = 15.0):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_klines(self, symbol: str, *, outputsize: int = 100) -> list[dict[str, Any]]:
        if symbol not in {"SPY", "QQQ"}:
            raise ValueError("unsupported cross-market ETF symbol")
        if not 8 <= outputsize <= 5000:
            raise ValueError("outputsize must be between 8 and 5000")
        try:
            response = self.session.get(
                TWELVE_DATA_URL,
                params={
                    "symbol": symbol,
                    "interval": INTERVAL,
                    "outputsize": outputsize,
                    "timezone": "UTC",
                    "order": "ASC",
                    "apikey": self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                raise CrossMarketDataError("Twelve Data rate limit reached") from exc
            raise CrossMarketDataError("Twelve Data intraday request failed") from exc
        except ValueError as exc:
            raise CrossMarketDataError("Twelve Data returned invalid JSON") from exc
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise CrossMarketDataError(str(payload.get("message") or "Twelve Data rejected the intraday request"))
        return normalize_twelve_data(payload, symbol)


def _closed_rows(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        try:
            timestamp = _parse_utc(row.get("timestamp"))
            close_time = _parse_utc(row.get("close_timestamp"))
            price = float(row.get("close"))
            if close_time <= now and math.isfinite(price) and price > 0:
                result.append({"timestamp": timestamp, "close_timestamp": close_time, "close": price})
        except (TypeError, ValueError, OverflowError):
            continue
    return sorted(result, key=lambda item: item["timestamp"])


def _pct_change(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 8:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    centered_left = [value - mean_left for value in left]
    centered_right = [value - mean_right for value in right]
    denom_left = math.sqrt(sum(value * value for value in centered_left))
    denom_right = math.sqrt(sum(value * value for value in centered_right))
    if denom_left == 0 or denom_right == 0:
        return None
    return sum(a * b for a, b in zip(centered_left, centered_right)) / (denom_left * denom_right)


def analyze_cross_market(
    candles: Mapping[str, list[dict[str, Any]]],
    *,
    now: datetime | None = None,
    max_age_minutes: int = 35,
) -> dict[str, Any]:
    """Calculate synchronized 15m/1h returns, correlations and a cautious regime label."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    required = ("BTCUSDT", "SPY", "QQQ")
    series = {symbol: _closed_rows(candles.get(symbol, []), reference) for symbol in required}
    unavailable = [symbol for symbol in required if len(series[symbol]) < 5]
    if unavailable:
        return {
            "status": "insufficient_data", "label": "Dades insuficients",
            "reason": "Calen almenys cinc espelmes tancades per a BTC, SPY i QQQ.",
            "unavailable": unavailable, "assets": {}, "correlations": {},
            "observed_at": reference.isoformat(),
        }

    latest_close_times = {symbol: rows[-1]["close_timestamp"] for symbol, rows in series.items()}
    oldest_latest_close = min(latest_close_times.values())
    newest_latest_close = max(latest_close_times.values())
    age_minutes = (reference - oldest_latest_close).total_seconds() / 60.0
    sync_minutes = (newest_latest_close - oldest_latest_close).total_seconds() / 60.0
    if age_minutes > max_age_minutes or sync_minutes > 30:
        return {
            "status": "stale_or_unsynchronized", "label": "Dades antigues o desalineades",
            "reason": "Les últimes espelmes tancades no són prou recents o no estan sincronitzades.",
            "unavailable": [], "assets": {}, "correlations": {},
            "latest_candle_close_utc": oldest_latest_close.isoformat(), "age_minutes": round(age_minutes, 1),
            "sync_difference_minutes": round(sync_minutes, 1), "observed_at": reference.isoformat(),
        }

    common = sorted(set.intersection(*[
        {row["timestamp"] for row in series[symbol]} for symbol in required
    ]))
    if len(common) < 8:
        return {
            "status": "insufficient_overlap", "label": "Historial sincronitzat insuficient",
            "reason": "No hi ha almenys vuit espelmes comunes entre els tres mercats.",
            "unavailable": [], "assets": {}, "correlations": {},
            "common_bars": len(common), "observed_at": reference.isoformat(),
        }
    lookup = {
        symbol: {row["timestamp"]: row["close"] for row in series[symbol]}
        for symbol in required
    }
    common = common[-100:]
    interval = timedelta(minutes=15)
    returns = {symbol: [] for symbol in required}
    valid_return_times = []
    for index in range(1, len(common)):
        current_time = common[index]
        previous_time = common[index - 1]
        # Do not treat overnight, weekend, holiday or missing-bar gaps as 15m returns.
        if current_time - previous_time != interval:
            continue
        valid_return_times.append(current_time)
        for symbol in required:
            change = _pct_change(lookup[symbol][current_time], lookup[symbol][previous_time])
            returns[symbol].append(change)

    latest = common[-1]
    previous_15m = latest - interval
    hourly_base = latest - timedelta(hours=1)
    hourly_path = [hourly_base + interval * step for step in range(5)]
    has_contiguous_hour = all(timestamp in lookup["BTCUSDT"] for timestamp in hourly_path)
    assets = {}
    for symbol in required:
        close = lookup[symbol][latest]
        prior = lookup[symbol].get(previous_15m)
        base = lookup[symbol].get(hourly_base) if has_contiguous_hour else None
        assets[symbol] = {
            "price": close,
            "return_15m_pct": _pct_change(close, prior) if prior is not None else None,
            "return_1h_pct": _pct_change(close, base) if base is not None else None,
            "latest_candle_utc": latest,
            "bars": len(common),
        }

    correlations = {
        "BTC_SPY_15m": _correlation(returns["BTCUSDT"][-24:], returns["SPY"][-24:]),
        "BTC_QQQ_15m": _correlation(returns["BTCUSDT"][-24:], returns["QQQ"][-24:]),
        "SPY_QQQ_15m": _correlation(returns["SPY"][-24:], returns["QQQ"][-24:]),
    }
    hourly = [assets[symbol]["return_1h_pct"] for symbol in required]
    if any(value is None for value in hourly):
        label, regime = "Dades horàries insuficients", "unknown"
    else:
        btc, spy, qqq = hourly
        if btc <= -0.8 and spy <= -0.35 and qqq <= -0.45:
            label, regime = "Risk-off sincronitzat", "risk_off"
        elif btc >= 0.8 and spy >= 0.35 and qqq >= 0.45:
            label, regime = "Risk-on sincronitzat", "risk_on"
        elif spy <= -0.35 and qqq <= -0.45 and btc > 0:
            label, regime = "Borsa feble / BTC resilient", "equity_weak_btc_resilient"
        elif btc < 0 and spy > 0 and qqq > 0:
            label, regime = "BTC feble / borsa resilient", "btc_weak_equities_resilient"
        elif (spy >= 0 and qqq < 0) or (spy < 0 and qqq >= 0):
            label, regime = "Divergència S&P 500 / Nasdaq", "equity_divergence"
        else:
            label, regime = "Mixt / sense confirmació", "mixed"

    return {
        "status": "ok", "regime": regime, "label": label,
        "reason": "Classificació descriptiva basada en rendiments de les últimes quatre espelmes tancades (1h). No és una ordre ni una predicció.",
        "assets": assets, "correlations": correlations,
        "common_bars": len(common), "latest_candle_utc": latest,
        "age_minutes": round(age_minutes, 1), "sync_difference_minutes": round(sync_minutes, 1),
        "observed_at": reference.isoformat(),
    }


def fetch_cross_market_candles(api_key: str, *, binance_client=None, twelve_client=None) -> dict[str, Any]:
    """Fetch BTCUSDT from Binance and SPY/QQQ from Twelve Data, preserving failures."""
    from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError

    binance = binance_client or BinanceMarketDataClient()
    twelve = twelve_client or TwelveDataIntradayClient(api_key)
    candles: dict[str, list[dict[str, Any]]] = {}
    unavailable = []
    try:
        candles["BTCUSDT"] = binance.get_klines("BTCUSDT", interval="15m", limit=100)
    except (BinanceMarketDataError, ValueError) as exc:
        unavailable.append({"symbol": "BTCUSDT", "source": "Binance", "reason": str(exc)})
    for symbol in ("SPY", "QQQ"):
        try:
            candles[symbol] = twelve.get_klines(symbol, outputsize=100)
        except (CrossMarketDataError, ValueError) as exc:
            unavailable.append({"symbol": symbol, "source": "Twelve Data", "reason": str(exc)})
    return {"candles": candles, "unavailable": unavailable, "observed_at": datetime.now(timezone.utc).isoformat()}
