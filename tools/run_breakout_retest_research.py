"""Read-only daily breakout-retest research; never connected to trading execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_markets.providers.binance import BinanceMarketDataClient, BinanceMarketDataError
from global_markets.statistical_intelligence import (
    closed_candles, _ema, _rsi, _atr, _sma,
)


def evaluate(candles, *, min_sample=30, retest_window=3, fee_per_side_pct=0.10,
             slippage_per_side_pct=0.05, volume_multiple=1.20,
             stop_buffer_atr=0.50, reward_risk=2.0, max_holding=5):
    """Breakout close -> retest within N bars -> directional rejection -> next-open entry.

    No same-bar breakout/retest. A long retest must trade into the prior high
    (within a small ATR tolerance), close back above it, and close green.
    Shorts are symmetric. A close through the level invalidates the setup.
    """
    if retest_window < 1 or max_holding < 1:
        raise ValueError("retest_window and max_holding must be positive")
    n = len(candles)
    close = [c["close"] for c in candles]
    volume = [float(c.get("volume", 0) or 0) for c in candles]
    ema50, ema200 = _ema(close, 50), _ema(close, 200)
    ema12, ema26 = _ema(close, 12), _ema(close, 26)
    macd = [ema12[i] - ema26[i] if ema12[i] is not None and ema26[i] is not None else None for i in range(n)]
    signal = _ema([v if v is not None else 0.0 for v in macd], 9)
    rsi, atr, vol_sma = _rsi(close), _atr(candles), _sma(volume, 20)
    split = int(n * 0.70)
    costs = 2 * (fee_per_side_pct + slippage_per_side_pct)
    trades = []
    i = 200
    while i < n - 2:
        prev, bar = candles[i - 1], candles[i]
        vals = (ema50[i], ema200[i], rsi[i], atr[i], vol_sma[i], macd[i], signal[i])
        if any(v is None for v in vals) or vol_sma[i] <= 0 or atr[i] <= 0:
            i += 1
            continue
        vol_ok = volume[i] >= vol_sma[i] * volume_multiple
        side = 1 if (bar["close"] > prev["high"] and bar["close"] > ema50[i] > ema200[i]
                     and 50 <= rsi[i] <= 70 and macd[i] > signal[i] and vol_ok) else (
               -1 if (bar["close"] < prev["low"] and bar["close"] < ema50[i] < ema200[i]
                     and 30 <= rsi[i] <= 50 and macd[i] < signal[i] and vol_ok) else 0)
        if not side:
            i += 1
            continue
        level = prev["high"] if side > 0 else prev["low"]
        found = None
        expired = min(i + retest_window, n - 2)
        for j in range(i + 1, expired + 1):
            test = candles[j]
            tolerance = atr[i] * 0.25
            if side > 0:
                invalid = test["close"] < level - tolerance
                touched = test["low"] <= level + tolerance
                rejected = test["close"] > level and test["close"] > test["open"]
            else:
                invalid = test["close"] > level + tolerance
                touched = test["high"] >= level - tolerance
                rejected = test["close"] < level and test["close"] < test["open"]
            if invalid:
                break
            if touched and rejected:
                found = j
                break
        if found is None:
            i = expired + 1
            continue
        entry_i = found + 1
        entry = candles[entry_i]["open"]
        # Structural stop beyond the retest candle and breakout level buffer.
        buffer = atr[found] * stop_buffer_atr
        stop = min(candles[found]["low"], level - buffer) if side > 0 else max(candles[found]["high"], level + buffer)
        risk = abs(entry - stop)
        if risk <= 0 or (side > 0 and stop >= entry) or (side < 0 and stop <= entry):
            i = entry_i
            continue
        target = entry + side * risk * reward_risk
        last_i = min(entry_i + max_holding - 1, n - 1)
        exit_price, reason, exit_i = candles[last_i]["close"], "time_exit", last_i
        for k in range(entry_i, last_i + 1):
            b = candles[k]
            # Gap-through stop executes at the worse opening price, not the stale stop.
            if side > 0 and b["open"] <= stop:
                exit_price, reason, exit_i = b["open"], "stop_gap", k
                break
            if side < 0 and b["open"] >= stop:
                exit_price, reason, exit_i = b["open"], "stop_gap", k
                break
            stop_hit = b["low"] <= stop if side > 0 else b["high"] >= stop
            target_hit = b["high"] >= target if side > 0 else b["low"] <= target
            if stop_hit:
                exit_price, reason, exit_i = stop, "stop_loss", k
                break
            if target_hit:
                exit_price, reason, exit_i = target, "take_profit", k
                break
        gross = (exit_price / entry - 1) * 100 * side
        trades.append({
            "breakout_date": candles[i].get("date"),
            "retest_date": candles[found].get("date"),
            "entry_date": candles[entry_i].get("date"),
            "exit_date": candles[exit_i].get("date"),
            "side": "long" if side > 0 else "short",
            "level": round(level, 8), "entry": round(entry, 8),
            "stop": round(stop, 8), "target": round(target, 8),
            "exit": round(exit_price, 8), "exit_reason": reason,
            "gross_return_pct": round(gross, 4),
            "net_return_pct": round(gross - costs, 4),
            "holdout": i >= split,
        })
        i = exit_i + 1

    def stats(items):
        returns = [t["net_return_pct"] for t in items]
        wins = [x for x in returns if x > 0]
        losses = [x for x in returns if x < 0]
        gp, gl = sum(wins), abs(sum(losses))
        return {
            "trades": len(items), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(items) * 100, 1) if items else None,
            "mean_net_return_pct": round(sum(returns) / len(returns), 3) if items else None,
            "profit_factor": round(gp / gl, 3) if gl else None,
            "sample_status": "usable_for_exploration" if len(items) >= min_sample else "small_sample",
            "exit_reasons": {r: sum(t["exit_reason"] == r for t in items)
                             for r in ("stop_loss", "stop_gap", "take_profit", "time_exit")},
        }
    return {
        "method": "daily_breakout_retest_next_open",
        "rules": {
            "confirmation": "Breakout candle closes beyond prior daily high/low with EMA50/200, RSI, MACD and volume confirmation.",
            "retest": f"Within {retest_window} subsequent candles; touch within 0.25 ATR of level, then close back through level in breakout direction with directional candle body.",
            "invalidation": "Close beyond breakout level by more than 0.25 ATR before retest.",
            "entry": "Open of candle after confirmed retest; no lookahead.",
            "stop": f"Beyond retest candle extreme and {stop_buffer_atr} ATR buffer from breakout level.",
            "target": f"{reward_risk}:1 risk/reward; max holding {max_holding} candles.",
            "cost_round_trip_pct": round(costs, 3),
            "same_candle_stop_and_target": "stop first",
            "gap_stop": "Exit at opening price when opening gaps through stop, before intraday range checks.",
        },
        "exploration": stats([t for t in trades if not t["holdout"]]),
        "holdout": stats([t for t in trades if t["holdout"]]),
        "trades": trades,
        "limitations": [
            "Research only; no scanner, paper ledger or execution connection.",
            "Daily OHLC cannot reveal intraday path; if stop and target both touch, stop is assumed first.",
            "Gap stop uses opening price but does not model additional spread or market impact.",
            "Fees/slippage are assumptions; no funding, spread dynamics or partial fills.",
            "One chronological holdout and small samples do not establish an edge.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only breakout-retest study")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "BONKUSDT", "WIFUSDT", "PUMPUSDT", "UNIUSDT", "NEARUSDT", "ZECUSDT", "AAVEUSDT", "PEPEUSDT"])
    parser.add_argument("--limit", type=int, default=5000, choices=(1000, 2000, 3000, 5000))
    parser.add_argument("--output", default="breakout_retest_report.json")
    args = parser.parse_args()
    client = BinanceMarketDataClient()
    assets, failures = [], []
    for symbol in args.symbols:
        try:
            rows = closed_candles(client.get_klines_history(symbol, interval="1d", total_limit=args.limit))
            assets.append({"symbol": symbol, "candles": len(rows),
                           "first_date": rows[0].get("date") if rows else None,
                           "last_date": rows[-1].get("date") if rows else None,
                           "breakout_retest": evaluate(rows)})
        except (BinanceMarketDataError, ValueError) as exc:
            failures.append({"symbol": symbol, "reason": str(exc)})
    payload = {"report_type": "read_only_breakout_retest_research", "assets": assets, "unavailable": failures}
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved {len(assets)} asset reports to {args.output}")
    return 0 if assets else 1


if __name__ == "__main__":
    raise SystemExit(main())
