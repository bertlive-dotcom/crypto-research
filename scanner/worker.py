"""Standalone five-minute scanner worker. Paper trading only; no exchange order API."""
from __future__ import annotations
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from trading_desk import Signal, ensure_position_ids, new_portfolio, paper_entry, update_position_from_candle, ensure_daily_equity_baseline, daily_equity_drawdown
from .config import (
    SCAN_INTERVAL_SECONDS, STARTING_CAPITAL_USD, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    MAX_DAILY_LOSS_USDT, QUOTE_ASSET,
)
from .market_data import BinanceSpotClient
from .market_scanner import scan_market, apply_paper_rules
from .store import ScannerStore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("market-scanner")
CANDLE_INTERVAL_MS = 300_000
MAX_CANDLE_AGE_MS = 600_000
KLINE_HISTORY_LIMIT = 1000


def _closed_candles_since(client, position: dict, now_ms: int) -> list[list]:
    """Return every consecutive, fully closed 5m candle after the durable checkpoint."""
    checkpoint = position.get("last_market_candle_close_ms")
    if checkpoint is None:
        raise ValueError("Position has no candle checkpoint; manual risk reconciliation is required.")
    checkpoint = int(checkpoint)
    symbol = str(position.get("market_symbol") or (str(position.get("asset", "")).upper() + QUOTE_ASSET))
    raw = client.klines(symbol, "5m", KLINE_HISTORY_LIMIT)
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("Insufficient 5m candle history")
    # Binance returns chronological klines and the final row is normally still forming.
    closed = [row for row in raw if int(row[6]) < now_ms]
    if not closed:
        raise ValueError("No fully closed 5m candle available")
    latest_close = int(closed[-1][6])
    if latest_close > now_ms or now_ms - latest_close > MAX_CANDLE_AGE_MS:
        raise ValueError("Latest closed 5m candle is stale or has an invalid close time")
    pending = [row for row in closed if int(row[6]) > checkpoint]
    if not pending:
        if latest_close < checkpoint:
            raise ValueError("Candle history is older than the saved checkpoint")
        return []
    # If the API's 1000-row window no longer reaches the checkpoint, fail closed.
    if int(pending[0][6]) != checkpoint + CANDLE_INTERVAL_MS:
        raise ValueError("Gap in 5m candle history since the saved checkpoint")
    previous_close = checkpoint
    for row in pending:
        close_ms = int(row[6])
        if close_ms - previous_close != CANDLE_INTERVAL_MS:
            raise ValueError("Non-consecutive 5m candle history")
        candle_open = float(row[1])
        high, low, close = float(row[2]), float(row[3]), float(row[4])
        if min(candle_open, high, low, close) <= 0 or low > min(candle_open, close) or high < max(candle_open, close):
            raise ValueError("Invalid OHLC candle values")
        previous_close = close_ms
    return pending


def run_once(store: ScannerStore, client: BinanceSpotClient | None = None) -> dict:
    worker_id = str(uuid.uuid4())
    if not store.acquire_lock(worker_id):
        log.info("Another scanner worker holds the lease; skipping this cycle.")
        return {"status": "locked"}
    try:
        portfolio = store.load_state() or new_portfolio(STARTING_CAPITAL_USD)
        previous_daily_risk = dict(portfolio.get("daily_risk") or {})
        ids_changed = ensure_position_ids(portfolio)
        ensure_daily_equity_baseline(portfolio)
        portfolio.setdefault("processed_signal_ids", [])
        if previous_daily_risk != portfolio.get("daily_risk", {}) or ids_changed:
            store.save_state(portfolio)

        client = client or BinanceSpotClient()
        closed = []
        unavailable_positions = []
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # Existing positions are always supervised before scanning for new opportunities.
        for position in list(portfolio.get("open_positions", [])):
            asset = str(position.get("asset", "")).upper()
            position_id = position.get("position_id")
            try:
                candles = _closed_candles_since(client, position, now_ms)
                for candle in candles:
                    trade = update_position_from_candle(
                        portfolio, asset, high=float(candle[2]), low=float(candle[3]),
                        close=float(candle[4]), open=float(candle[1]),
                        position_id=position_id,
                    )
                    # Advance the checkpoint only after this candle was safely evaluated.
                    if trade:
                        closed.append({
                            "asset": trade["asset"], "reason": trade["exit_reason"],
                            "pnl_usd": trade["realized_pnl_usd"],
                        })
                        break
                    position["last_market_candle_close_ms"] = int(candle[6])
                else:
                    continue
                # Position closed; no further candles need to be applied to it.
            except Exception as exc:
                unavailable_positions.append(str(position_id or asset or "unknown"))
                log.error("Position %s is not safely supervised; new entries will be blocked: %s",
                          position_id or asset, exc)
        portfolio["market_data_unavailable_positions"] = unavailable_positions

        # A scanner outage must not prevent position supervision or persistence.
        scan_error = None
        try:
            candidates, run = scan_market(client)
        except Exception as exc:
            candidates, run = [], {"analysed_count": 0, "candidate_count": 0}
            scan_error = str(exc)
            log.exception("Market scan failed after position supervision; no new entries this cycle.")

        approved = [] if unavailable_positions or scan_error else apply_paper_rules(candidates, portfolio)
        signals = []
        processed = set(portfolio["processed_signal_ids"])
        for row in approved:
            signal_id = f'{row["symbol"]}:1h:{row["features"]["1h"]["candle_close_time"]}:long'
            if signal_id in processed:
                continue
            try:
                # Establish the first checkpoint immediately before entry, so no
                # pre-entry candle is replayed against the new paper position.
                raw = client.klines(row["symbol"], "5m", 3)
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                closed_rows = [item for item in raw if int(item[6]) < now_ms]
                if not closed_rows or now_ms - int(closed_rows[-1][6]) > MAX_CANDLE_AGE_MS:
                    raise ValueError("Cannot establish a fresh 5m candle checkpoint for entry")
                checkpoint = int(closed_rows[-1][6])
                signal = Signal(
                    asset=row["base_asset"], market="major", price_usd=float(row["price_usdt"]),
                    volume_24h_usd=float(row["quote_volume_24h"]),
                    source="Market Scanner v1 / Binance Spot", scanner_approved=True,
                )
                position = paper_entry(portfolio, signal, stop_loss_pct=STOP_LOSS_PCT,
                    take_profit_pct=TAKE_PROFIT_PCT, direction="long")
                position["market_symbol"] = row["symbol"]
                position["last_market_candle_close_ms"] = checkpoint
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                log.warning("Paper entry rejected for %s: %s", row.get("symbol"), exc)
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
        if scan_error:
            run["scan_error"] = scan_error
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
