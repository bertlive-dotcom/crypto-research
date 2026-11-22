"""Read-only Binance Spot daily history and forecast orchestration.

This module is intentionally separate from the Market Scanner and Trading Desk.
It only reads public Spot klines; it has no account, order, persistence, or
execution functionality.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from portfolio_engine.forecast.model import forecast_latest

# Canonical watchlist symbol -> Binance Spot pair. Never substitute a different
# quote asset or provider symbol when a pair is unavailable.
BINANCE_SPOT_PAIRS = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "LINKUSD": "LINKUSDT", "XLMUSD": "XLMUSDT", "SUIUSD": "SUIUSDT",
    "HYPEUSD": "HYPEUSDT", "XMRUSD": "XMRUSDT", "LEOUSD": "LEOUSDT",
    "BATUSD": "BATUSDT", "PEPEUSD": "PEPEUSDT", "BEAMUSD": "BEAMUSDT",
    "ANVLUSD": "ANVLUSDT",
}
DEFAULT_WATCHLIST = tuple(BINANCE_SPOT_PAIRS)


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _closed_daily_rows(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    closed = []
    for row in rows:
        try:
            close_time = datetime.fromisoformat(str(row["close_timestamp"]).replace("Z", "+00:00"))
            if close_time.tzinfo is None:
                raise ValueError("candle close timestamp must be timezone-aware")
            close = float(row["close"])
            date = str(row["date"])
            datetime.strptime(date, "%Y-%m-%d")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Binance returned malformed daily candle data") from exc
        if close <= 0 or not close < float("inf"):
            raise ValueError("daily close prices must be finite and positive")
        if close_time.astimezone(timezone.utc) <= now:
            closed.append({"date": date, "close": close})
    closed.sort(key=lambda item: item["date"])
    dates = [item["date"] for item in closed]
    if len(dates) != len(set(dates)):
        raise ValueError("daily history contains duplicate dates")
    for previous, current in zip(dates, dates[1:]):
        delta = (datetime.strptime(current, "%Y-%m-%d") - datetime.strptime(previous, "%Y-%m-%d")).days
        if delta != 1:
            raise ValueError("daily history contains missing calendar days")
    return closed


def fetch_daily_close_series(
    symbols: Iterable[str] | None = None, *, client: Any | None = None,
    limit: int = 1000, min_observations: int = 120,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch closed daily closes for listed Spot pairs; preserve per-asset failures.

    The optional client follows the read-only BinanceMarketDataClient interface.
    The default client is imported lazily from the existing public data adapter.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if min_observations < 40:
        raise ValueError("min_observations must be at least 40")
    reference_time = _utc_now(now)
    requested = [str(symbol).upper() for symbol in (symbols if symbols is not None else DEFAULT_WATCHLIST)]
    if len(requested) != len(set(requested)):
        raise ValueError("requested symbols must be unique")
    if client is None:
        from global_markets.providers.binance import BinanceMarketDataClient
        client = BinanceMarketDataClient()

    result: dict[str, Any] = {
        "source": "binance_spot", "interval": "1d", "observed_at": reference_time.isoformat(),
        "read_only": True, "requested_symbols": requested, "series": {}, "unavailable": [],
    }
    try:
        listings = client.get_spot_symbol_status()
    except Exception as exc:
        result["unavailable"] = [
            {"symbol": symbol, "reason": "spot_listing_check_failed", "detail": str(exc)}
            for symbol in requested
        ]
        return result

    for canonical in requested:
        pair = BINANCE_SPOT_PAIRS.get(canonical)
        if pair is None:
            result["unavailable"].append({"symbol": canonical, "reason": "no_binance_pair_mapping"})
            continue
        listing = listings.get(pair)
        if listing is None:
            result["unavailable"].append({
                "symbol": canonical, "provider_symbol": pair, "reason": "pair_not_listed_on_binance_spot"
            })
            continue
        if listing.get("status") != "TRADING" or listing.get("spot_allowed") is not True:
            result["unavailable"].append({
                "symbol": canonical, "provider_symbol": pair, "reason": "pair_not_active_for_spot_trading"
            })
            continue
        try:
            raw_rows = client.get_klines(pair, interval="1d", limit=limit)
            rows = _closed_daily_rows(raw_rows, reference_time)
            if len(rows) < min_observations:
                raise ValueError("insufficient_closed_daily_history")
            result["series"][canonical] = {
                "provider_symbol": pair, "dates": [row["date"] for row in rows],
                "closes": [row["close"] for row in rows], "observations": len(rows),
                "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
            }
        except Exception as exc:
            reason = str(exc) if str(exc) == "insufficient_closed_daily_history" else "history_fetch_or_validation_failed"
            result["unavailable"].append({
                "symbol": canonical, "provider_symbol": pair, "reason": reason, "detail": str(exc),
            })
    result["summary"] = {
        "requested": len(requested), "available": len(result["series"]),
        "unavailable": len(result["unavailable"]),
        "observations": sum(item["observations"] for item in result["series"].values()),
    }
    return result


def forecast_watchlist_from_binance(
    symbols: Iterable[str] | None = None, *, client: Any | None = None,
    limit: int = 1000, min_observations: int = 120, horizon: int = 7,
    min_train_samples: int = 30, min_validation_samples: int = 20,
    alpha: float = 10.0, now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch history and produce per-asset walk-forward-calibrated forecasts."""
    history = fetch_daily_close_series(
        symbols, client=client, limit=limit, min_observations=min_observations, now=now,
    )
    forecasts: dict[str, Any] = {}
    unavailable = list(history["unavailable"])
    for symbol, series in history["series"].items():
        try:
            forecasts[symbol] = forecast_latest(
                series["closes"], horizon=horizon, min_train_samples=min_train_samples,
                min_validation_samples=min_validation_samples, alpha=alpha,
            )
            forecasts[symbol].update({
                "provider_symbol": series["provider_symbol"], "data_source": history["source"],
                "history_first_date": series["first_date"], "history_last_date": series["last_date"],
                "history_observations": series["observations"],
            })
        except (ValueError, ArithmeticError) as exc:
            unavailable.append({
                "symbol": symbol, "provider_symbol": series["provider_symbol"],
                "reason": "forecast_validation_failed", "detail": str(exc),
            })
    return {
        "source": history["source"], "observed_at": history["observed_at"],
        "read_only": True, "forecasts": forecasts, "unavailable": unavailable,
        "summary": {
            "requested": len(history["requested_symbols"]), "forecasted": len(forecasts),
            "view_eligible": sum(bool(item["view_eligible"]) for item in forecasts.values()),
            "unavailable": len(unavailable),
        },
    }
