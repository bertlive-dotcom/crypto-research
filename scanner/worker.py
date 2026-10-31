"""Standalone five-minute scanner worker. Paper trading only; no exchange order API."""
from __future__ import annotations
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from trading_desk import Signal, new_portfolio, paper_entry, update_position_mark
from .config import (
    SCAN_INTERVAL_SECONDS, STARTING_CAPITAL_USD, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
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
        portfolio.setdefault("processed_signal_ids", [])
        client = client or BinanceSpotClient()
        candidates, run = scan_market(client)

        prices = client.prices()
        closed = []
        for position in list(portfolio.get("open_positions", [])):
            price = prices.get(position["asset"].upper())
            if price:
                trade = update_position_mark(portfolio, position["asset"], float(price))
                if trade:
                    closed.append({"asset": trade["asset"], "reason": trade["exit_reason"], "pnl_usd": trade["realized_pnl_usd"]})

        approved = apply_paper_rules(candidates, portfolio)
        signals = []
        processed = set(portfolio["processed_signal_ids"])
        for row in approved:
            signal_id = f'{row["symbol"]}:1h:{row["features"]["1h"]["candle_close_time"]}:long'
            if signal_id in processed:
                continue
            signal = Signal(
                asset=row["base_asset"], market="major", price_usd=float(row["price_usdt"]),
                volume_24h_usd=float(row["quote_volume_24h"]),
                gain_45m_pct=None, source="Market Scanner v1 / Binance Spot",
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
        run.update({
            "paper_entries": len(signals), "paper_exits": closed,
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
