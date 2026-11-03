"""Standalone five-minute scanner worker. Paper trading only; no exchange order API."""
from __future__ import annotations
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from trading_desk import Signal, ensure_position_ids, new_portfolio, paper_entry, update_position_from_candle, ensure_daily_equity_baseline, daily_equity_drawdown
from .config import (
    SCAN_INTERVAL_SECONDS, STARTING_CAPITAL_USD, STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DAILY_LOSS_USDT,
)
from .market_data import BinanceSpotClient
from .market_scanner import scan_market, apply_paper_rules
from .store import ScannerStore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("market-scanner")

def run_once(store: ScannerStore, client: BinanceSpotClient | None = None) -> dict:
    worker_id = str(uuid.uuid4())
    if not store.acquire_lock(worker_id):
        log.info("Another scanner worker holds the lease; skipping this cycle.")
        return {"status": "locked"}
    try:
        portfolio = store.load_state() or new_portfolio(STARTING_CAPITAL_USD)
        # Persist opening equity and stable legacy IDs before any fallible market-data work.
        previous_daily_risk = dict(portfolio.get("daily_risk") or {})
        ids_changed = ensure_position_ids(portfolio)
        ensure_daily_equity_baseline(portfolio)
        portfolio.setdefault("processed_signal_ids", [])
        if previous_daily_risk != portfolio.get("daily_risk", {}) or ids_changed:
            # Fail the cycle closed if the baseline cannot be made durable.
            store.save_state(portfolio)
        client = client or BinanceSpotClient()
        candidates, run = scan_market(client)

        closed = []
        unavailable_positions = []
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # Use the latest fully closed 5m candle for every open position. A missing
        # or stale candle makes portfolio risk unavailable and blocks new entries.
        for position in list(portfolio.get("open_positions", [])):
            asset = str(position.get("asset", "")).upper()
            try:
                raw = client.klines(asset + "USDT", "5m", 3)
                if len(raw) < 2:
                    raise ValueError("Insufficient 5m candles")
                candle = raw[-2]  # Binance's final row is the still-forming candle.
                candle_open_ms, candle_close_ms = int(candle[0]), int(candle[6])
                if candle_close_ms > now_ms or now_ms - candle_close_ms > 600_000:
                    raise ValueError("Latest closed 5m candle is stale or has an invalid close time")
                trade = update_position_from_candle(
                    portfolio, asset, high=float(candle[2]), low=float(candle[3]),
                    close=float(candle[4]), open=float(candle[1]),
                    position_id=position.get("position_id"),
                )
                position["last_market_candle_close_ms"] = candle_close_ms
                position["last_market_candle_open_ms"] = candle_open_ms
                if trade:
                    closed.append({"asset": trade["asset"], "reason": trade["exit_reason"], "pnl_usd": trade["realized_pnl_usd"]})
            except Exception as exc:
                unavailable_positions.append(str(position.get("position_id") or asset or "unknown"))
                log.error("Position %s is not safely supervised; new entries will be blocked: %s",
                          position.get("position_id") or asset, exc)
        portfolio["market_data_unavailable_positions"] = unavailable_positions

        approved = [] if unavailable_positions else apply_paper_rules(candidates, portfolio)
        signals = []
        processed = set(portfolio["processed_signal_ids"])
        for row in approved:
            signal_id = f'{row["symbol"]}:1h:{row["features"]["1h"]["candle_close_time"]}:long'
            if signal_id in processed:
                continue
            signal = Signal(
                asset=row["base_asset"], market="major", price_usd=float(row["price_usdt"]),
                volume_24h_usd=float(row["quote_volume_24h"]),
                source="Market Scanner v1 / Binance Spot", scanner_approved=True,
            )
            try:
                position = paper_entry(portfolio, signal, stop_loss_pct=STOP_LOSS_PCT,
                    take_profit_pct=TAKE_PROFIT_PCT, direction="long")
            except ValueError as exc:
                log.warning("Paper entry rejected for %s: %s", row["symbol"], exc)
                continue
            processed.add(signal_id)
            signals.append({
                "signal_id": signal_id, "symbol": row["symbol"], "direction": "long",
                "score": row["score"], "status": "paper_opened", "price_usdt": row["price_usdt"],
                "stop_price": position["stop_price"], "take_profit_price": position["take_profit_price"],
                "position": position, "reasons": row["reasons"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        portfolio["processed_signal_ids"] = sorted(processed)[-1000:]
        daily_risk = daily_equity_drawdown(portfolio)
        run.update({
            "paper_entries": len(signals), "paper_exits": closed,
            "daily_risk": daily_risk, "daily_loss_limit_usd": MAX_DAILY_LOSS_USDT,
            "worker_id": worker_id, "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        store.save_cycle(portfolio, run, candidates, signals)
        log.info("Cycle complete: analysed=%s candidates=%s entries=%s exits=%s",
            run["analysed_count"], run["candidate_count"], len(signals), len(closed))
        return run
    finally:
        try:
            store.release_lock(worker_id)
        except Exception:
            log.exception("Could not release scanner lease; it will expire automatically.")

def main():
    store = ScannerStore()
    client = BinanceSpotClient()
    log.info("Market Scanner v1 started; interval=%ss; paper-only mode.", SCAN_INTERVAL_SECONDS)
    while True:
        started = time.monotonic()
        try:
            run_once(store, client)
        except Exception:
            log.exception("Scanner cycle failed; no live orders were sent.")
        elapsed = time.monotonic() - started
        time.sleep(max(5, SCAN_INTERVAL_SECONDS - elapsed))

if __name__ == "__main__":
    main()
