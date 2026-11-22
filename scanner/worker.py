"""Standalone five-minute scanner worker. Paper trading only; no exchange order API."""
from __future__ import annotations
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from trading_desk import Signal, new_portfolio, paper_entry, update_position_from_candle
from .config import (
    SCAN_INTERVAL_SECONDS, STARTING_CAPITAL_USD, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    validate_staging_target,
)
from .agents import run_agent_pipeline
from .market_data import BinanceSpotClient
from .market_scanner import scan_market
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

        closed = []
        for position in list(portfolio.get("open_positions", [])):
            # Evaluate the latest completed 5m OHLC candle, not a single sampled
            # ticker price: this catches intrabar SL/TP touches between worker cycles.
            symbol = f'{position["asset"].upper()}USDT'
            try:
                candles = client.klines(symbol, "5m", 2)
                if len(candles) < 2:
                    continue
                candle = candles[-2]  # Binance's final row is the still-forming candle.
                if len(candle) < 7:
                    log.warning("Skipping %s exit check: incomplete Binance kline.", symbol)
                    continue
                trade = update_position_from_candle(
                    portfolio, position["asset"],
                    high=float(candle[2]), low=float(candle[3]),
                    close=float(candle[4]), open_price=float(candle[1]),
                    position_id=position.get("position_id"),
                )
                if trade:
                    closed.append({"asset": trade["asset"], "reason": trade["exit_reason"],
                                   "pnl_usd": trade["realized_pnl_usd"]})
            except Exception as exc:
                # Fail closed for exits: retain the position until a valid OHLC
                # candle is available rather than treating a missing quote as safe.
                log.warning("Could not evaluate paper exits for %s: %s", symbol, exc)

        # Six deterministic stages; existing Market Scanner risk rules remain authoritative.
        pipeline = run_agent_pipeline(candidates, portfolio, mode="paper")
        approved = pipeline["approved_candidates"]
        signals = []
        processed = set(portfolio["processed_signal_ids"])
        for row in approved:
            signal_id = f'{row["symbol"]}:1h:{row["features"]["1h"]["candle_close_time"]}:long'
            if signal_id in processed:
                continue
            signal = Signal(
                asset=row["base_asset"], market="major", price_usd=float(row["price_usdt"]),
                volume_24h_usd=float(row["quote_volume_24h"]),
                # Percent return over the two most recent CLOSED 1h candles.
                # This is a percentage value (2.0 == +2%), not a decimal fraction.
                gain_1h_pct=row.get("features", {}).get("1h", {}).get("change_pct"),
                source="Market Scanner v1 / Binance Spot / six-agent pipeline",
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
                "agent_pipeline": pipeline["agents"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        portfolio["processed_signal_ids"] = sorted(processed)[-1000:]
        run.update({
            "paper_entries": len(signals), "paper_exits": closed,
            "worker_id": worker_id, "completed_at": datetime.now(timezone.utc).isoformat(),
            "agent_pipeline": {
                "mode": pipeline["mode"],
                "agents": pipeline["agents"],
                "candidate_count": pipeline["candidate_count"],
                "scouted_count": pipeline["scouted_count"],
                "filtered_count": pipeline["filtered_count"],
                "risk_approved_count": pipeline["risk_approved_count"],
                "authorized_count": pipeline["authorized_count"],
                "audit": pipeline["audit"],
            },
        })
        store.save_cycle(portfolio, run, candidates, signals)
        log.info(
            "Cycle complete: analysed=%s candidates=%s six_agent_authorized=%s entries=%s exits=%s",
            run["analysed_count"], run["candidate_count"],
            pipeline["authorized_count"], len(signals), len(closed),
        )
        return run
    finally:
        try:
            store.release_lock(worker_id)
        except Exception:
            log.exception("Could not release scanner lease; it will expire automatically.")


def main():
    validate_staging_target()
    store = ScannerStore()
    client = BinanceSpotClient()
    log.info("Market Scanner v1 with six-agent paper pipeline started; interval=%ss; paper-only mode.", SCAN_INTERVAL_SECONDS)
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
