"""Candidate discovery, technical scoring and deterministic paper-entry decisions."""
from __future__ import annotations
from datetime import datetime, timezone
from .config import (
    AUTO_ENTRY_SCORE, MAX_CANDIDATES, MIN_SCORE, WATCHLIST,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_OPEN_POSITIONS, MAX_DAILY_LOSS_USDT,
)
from .indicators import atr_pct, candle_series, ema, macd_histogram, rsi, volume_ratio
from .market_data import BinanceSpotClient

def _features(raw: list[list]) -> dict:
    c = candle_series(raw)
    closes, highs, lows, volumes = c["close"], c["high"], c["low"], c["volume"]
    if len(closes) < 60:
        raise ValueError("Insufficient closed candles")
    e20, e50 = ema(closes, 20), ema(closes, 50)
    return {
        "close": closes[-1], "ema20": e20[-1] if e20 else None,
        "ema50": e50[-1] if e50 else None, "rsi14": rsi(closes),
        "macd_hist": macd_histogram(closes), "atr_pct": atr_pct(highs, lows, closes),
        "volume_ratio": volume_ratio(volumes),
        "candle_close_time": c["open_time"][-1],
    }

def score_candidate(ticker: dict, one_hour: dict, four_hour: dict, daily: dict) -> dict:
    price = float(ticker["price_usdt"])
    trend = one_hour["close"] > one_hour["ema20"] > one_hour["ema50"]
    momentum = one_hour["macd_hist"] is not None and one_hour["macd_hist"] > 0
    rsi_value = one_hour["rsi14"]
    rsi_ok = rsi_value is not None and 48 <= rsi_value <= 70
    volume = one_hour["volume_ratio"]
    volume_ok = volume is not None and volume >= 1.2
    multi_tf = four_hour["close"] > four_hour["ema20"] and daily["close"] > daily["ema20"]
    atr = one_hour["atr_pct"]
    volatility_ok = atr is not None and 0.5 <= atr <= 8.0
    extension_pct = ((price / one_hour["ema20"]) - 1.0) * 100.0 if one_hour["ema20"] > 0 else float("inf")
    not_extended = 0.0 <= extension_pct <= 4.0
    # Hard entry gates are deliberately separate from the weighted score.
    hard_checks_pass = trend and volume_ok and multi_tf and volatility_ok and not_extended
    parts = {
        "trend": 25 if trend else 0,
        "momentum": 20 if momentum and rsi_ok else (10 if momentum or rsi_ok else 0),
        "volume": 20 if volume_ok else 0,
        "multi_timeframe": 15 if multi_tf else 0,
        "volatility": 10 if volatility_ok else 0,
        "entry_risk": 10 if not_extended else 0,
    }
    score = sum(parts.values())
    reasons = []
    if not trend: reasons.append("1h trend not aligned (close > EMA20 > EMA50)")
    if not momentum: reasons.append("1h MACD histogram not positive")
    if not rsi_ok: reasons.append("1h RSI outside preferred 48-70 range")
    if not volume_ok: reasons.append("1h relative volume below 1.2x")
    if not multi_tf: reasons.append("4h and daily trend confirmation missing")
    if not volatility_ok: reasons.append("ATR outside 0.5%-8% range")
    if not not_extended: reasons.append("Price extended more than 4% above 1h EMA20")
    return {
        **ticker, "score": score, "score_components": parts, "eligible": score >= MIN_SCORE,
        "auto_entry_eligible": score >= AUTO_ENTRY_SCORE and hard_checks_pass,
        "hard_checks_pass": hard_checks_pass,
        "features": {"1h": one_hour, "4h": four_hour, "1d": daily},
        "reasons": reasons, "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

def scan_market(client: BinanceSpotClient | None = None) -> tuple[list[dict], dict]:
    client = client or BinanceSpotClient()
    tickers = client.universe()
    candidates = []
    errors = []
    watch = set(WATCHLIST)
    for ticker in tickers:
        try:
            symbol = ticker["symbol"]
            h1 = _features(client.klines(symbol, "1h", 100))
            h4 = _features(client.klines(symbol, "4h", 100))
            d1 = _features(client.klines(symbol, "1d", 100))
            candidates.append(score_candidate(ticker, h1, h4, d1))
        except Exception as exc:
            errors.append({"symbol": ticker.get("symbol"), "error": str(exc)[:240]})
    candidates.sort(key=lambda x: (x["score"], x["quote_volume_24h"]), reverse=True)
    # Keep up to 20 overall, while ensuring priority watchlist assets remain visible.
    selected = candidates[:MAX_CANDIDATES]
    selected_symbols = {x["symbol"] for x in selected}
    for row in candidates:
        if row["symbol"] in watch and row["symbol"] not in selected_symbols:
            selected.append(row)
            selected_symbols.add(row["symbol"])
    run = {
        "status": "completed" if candidates else "empty",
        "universe_size": len(tickers), "analysed_count": len(candidates),
        "candidate_count": len(selected), "error_count": len(errors),
        "errors": errors[:30], "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
    return selected, run

def daily_realized_pnl(portfolio: dict) -> float:
    today = datetime.now(timezone.utc).date()
    total = 0.0
    for trade in portfolio.get("closed_trades", []):
        closed = trade.get("closed_at", "")
        try:
            if datetime.fromisoformat(closed.replace("Z", "+00:00")).date() == today:
                total += float(trade.get("realized_pnl_usd", 0.0))
        except (ValueError, TypeError):
            continue
    return total

def apply_paper_rules(candidates: list[dict], portfolio: dict) -> list[dict]:
    """Return approved candidates; callers pass them to the existing paper_entry engine."""
    if len(portfolio.get("open_positions", [])) >= MAX_OPEN_POSITIONS:
        return []
    if daily_realized_pnl(portfolio) <= -MAX_DAILY_LOSS_USDT:
        return []
    open_assets = {p["asset"].upper() for p in portfolio.get("open_positions", [])}
    approved = []
    for row in candidates:
        if not row.get("auto_entry_eligible"):
            continue
        asset = row["base_asset"]
        if asset.upper() in open_assets:
            continue
        approved.append(row)
        open_assets.add(asset.upper())
        if len(open_assets) >= MAX_OPEN_POSITIONS:
            break
    return approved
