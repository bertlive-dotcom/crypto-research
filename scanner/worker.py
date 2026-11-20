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
    validate_staging_target,
)
from .agents import run_agent_pipeline
from .market_data import BinanceSpotClient
from .market_scanner import scan_market
from .risk_guard import evaluate_risk_guard
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
        # First mark every open position without triggering exits. This lets the
        # aggregate floating-loss guard see the full portfolio before a stop
        # closes individual positions in this same cycle.
        marked_prices = {}
        for position in list(portfolio.get("open_positions", [])):
            price = prices.get(position["asset"].upper())
            if price:
                marked_prices[position.get("position_id") or position["asset"]] = float(price)
                position["last_price_usd"] = float(price)

        pre_exit_guard = evaluate_risk_guard(portfolio)

        # Process stop-loss/take-profit exits after the pre-exit floating-loss check.
        for position in list(portfolio.get("open_positions", [])):
            price = marked_prices.get(position.get("position_id") or position["asset"])
            if price is not None:
                trade = update_position_mark(portfolio, position["asset"], price,
                                             position_id=position.get("position_id"))
                if trade:
                    closed.append({"asset": trade["asset"], "reason": trade["exit_reason"], "pnl_usd": trade["realized_pnl_usd"]})

        # Recalculate realized daily loss and drawdown after exits. Preserve any
        # floating-loss block detected immediately before those exits.
        risk_guard = evaluate_risk_guard(portfolio)
        risk_guard["pre_exit_floating_pnl_usd"] = pre_exit_guard["floating_pnl_usd"]
        risk_guard["pre_exit_floating_loss_limit_usd"] = pre_exit_guard["floating_loss_limit_usd"]
        combined_reasons = list(dict.fromkeys(
            pre_exit_guard["blocked_reasons"] + risk_guard["blocked_reasons"]
        ))
        risk_guard["blocked_reasons"] = combined_reasons
        risk_guard["can_open_new_positions"] = not combined_reasons
        permitted_candidates = candidates if risk_guard["can_open_new_positions"] else []
        if not risk_guard["can_open_new_positions"]:
            log.warning("Prop-Firm Risk Guard blocked new entries: %s", "; ".join(risk_guard["blocked_reasons"]))

        # Six deterministic stages remain unchanged; the guard is an additional outer gate.
        pipeline = run_agent_pipeline(permitted_candidates, portfolio, mode="paper")
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
            "risk_guard": risk_guard,
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
            "Cycle complete: analysed=%s candidates=%s risk_guard_allowed=%s six_agent_authorized=%s entries=%s exits=%s",
            run["analysed_count"], run["candidate_count"], risk_guard["can_open_new_positions"],
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
    log.info("Market Scanner v1 with six-agent paper pipeline and portfolio risk guard started; interval=%ss; paper-only mode.", SCAN_INTERVAL_SECONDS)
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
