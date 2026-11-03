"""Deterministic, simulation-only trading desk primitives.

No exchange execution, wallet signing, private keys, or external API calls live here.

Deployment sync marker: position-id migration support is included in this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import floor
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

STARTING_CAPITAL_USD = 80.0
MAX_TOP10_HOLDER_PCT = 40.0
MAX_DEV_WALLET_PCT = 8.0
MIN_SOLANA_LIQUIDITY_USD = 30_000.0
MAX_GAIN_45M_PCT = 80.0
MAX_MAJOR_GAIN_1H_PCT = 80.0
MIN_MAJOR_VOLUME_24H_USD = 1_000_000.0
DEFAULT_RISK_FRACTION = 0.01
MAX_POSITION_FRACTION = 0.10
MAX_TOTAL_EXPOSURE_FRACTION = 0.25
DEFAULT_FEE_RATE = 0.001
DEFAULT_SLIPPAGE_RATE = 0.003

@dataclass
class Signal:
    asset: str
    market: str
    price_usd: float
    liquidity_usd: Optional[float] = None
    top10_holder_pct: Optional[float] = None
    dev_wallet_pct: Optional[float] = None
    bundled_buys_first_60s: Optional[bool] = None
    gain_45m_pct: Optional[float] = None
    source_wallet_sold: Optional[bool] = None
    volume_24h_usd: Optional[float] = None
    gain_1h_pct: Optional[float] = None
    source: str = "manual"
    scanner_approved: bool = False
    observed_at: str = ""

    def __post_init__(self):
        if not self.observed_at:
            self.observed_at = datetime.now(timezone.utc).isoformat()

def evaluate_signal(signal: Signal) -> dict:
    """Apply deterministic eligibility checks; missing Solana data fails closed."""
    reasons = []
    if not signal.asset.strip():
        reasons.append("Asset identifier is missing.")
    if signal.price_usd <= 0:
        reasons.append("Price must be greater than zero.")
    if signal.market == "solana":
        required = {
            "liquidity": signal.liquidity_usd,
            "top-10 holder concentration": signal.top10_holder_pct,
            "developer wallet share": signal.dev_wallet_pct,
            "bundled-buy check": signal.bundled_buys_first_60s,
            "45-minute price change": signal.gain_45m_pct,
            "source-wallet status": signal.source_wallet_sold,
        }
        for label, value in required.items():
            if value is None:
                reasons.append(f"Missing {label} data; Solana signal rejected.")
        if signal.liquidity_usd is not None and signal.liquidity_usd < MIN_SOLANA_LIQUIDITY_USD:
            reasons.append(f"Liquidity below ${MIN_SOLANA_LIQUIDITY_USD:,.0f}.")
        if signal.top10_holder_pct is not None and signal.top10_holder_pct > MAX_TOP10_HOLDER_PCT:
            reasons.append(f"Top-10 holders exceed {MAX_TOP10_HOLDER_PCT:.0f}%.")
        if signal.dev_wallet_pct is not None and signal.dev_wallet_pct > MAX_DEV_WALLET_PCT:
            reasons.append(f"Developer wallet exceeds {MAX_DEV_WALLET_PCT:.0f}%.")
        if signal.bundled_buys_first_60s is True:
            reasons.append("Bundled buys detected in the first 60 seconds.")
        if signal.gain_45m_pct is not None and signal.gain_45m_pct > MAX_GAIN_45M_PCT:
            reasons.append(f"Token already gained more than {MAX_GAIN_45M_PCT:.0f}% in 45 minutes.")
        if signal.source_wallet_sold is True:
            reasons.append("Source wallet has already sold.")
    elif signal.market == "major":
        if signal.volume_24h_usd is None:
            reasons.append("Missing 24-hour volume; major-asset signal rejected.")
        elif signal.volume_24h_usd < MIN_MAJOR_VOLUME_24H_USD:
            reasons.append(f"24-hour volume below ${MIN_MAJOR_VOLUME_24H_USD:,.0f}.")
        # The scanner has already applied its own closed-candle, multi-timeframe
        # hard filters. Only its exact internal source may use this path.
        scanner_path = (
            signal.scanner_approved is True
            and signal.source == "Market Scanner v1 / Binance Spot"
        )
        if not scanner_path:
            major_gain = signal.gain_1h_pct
            # Backward compatibility for callers that still submit the old field.
            if major_gain is None:
                major_gain = signal.gain_45m_pct
            if major_gain is None:
                reasons.append("Missing 1-hour price change; major-asset signal rejected.")
            elif major_gain > MAX_MAJOR_GAIN_1H_PCT:
                reasons.append("Asset gained more than 80% in 1 hour; reject late entry.")
        elif signal.gain_1h_pct is not None and signal.gain_1h_pct > MAX_MAJOR_GAIN_1H_PCT:
            reasons.append("Asset gained more than 80% in 1 hour; reject late entry.")
    else:
        reasons.append("Unknown market. Use 'solana' or 'major'.")
    return {"approved": not reasons, "reasons": reasons, "checks_passed": 0 if reasons else (6 if signal.market == "solana" else 2)}

def position_risk_at_stop(position: dict, fee_rate: float = DEFAULT_FEE_RATE,
                           slippage_rate: float = DEFAULT_SLIPPAGE_RATE) -> dict:
    """Estimate net USD loss if the stored stop executes, including both-side costs."""
    stop = position.get("stop_price")
    if stop is None or float(stop) <= 0:
        raise ValueError("Position has no valid stop price; risk cannot be calculated.")
    result = mark_position(position, float(stop), fee_rate=fee_rate, slippage_rate=slippage_rate)
    risk_usd = max(0.0, -float(result["unrealized_pnl_usd"]))
    notional = float(position.get("notional_usd", 0.0))
    return {
        "risk_at_stop_usd": risk_usd,
        "risk_at_stop_pct_equity": None,
        "risk_at_stop_pct_notional": (risk_usd / notional * 100.0) if notional > 0 else None,
        "estimated_stop_exit_fill_usd": result["estimated_exit_fill_usd"],
    }


def size_position(capital_usd: float, stop_loss_pct: float, open_exposure_usd: float = 0.0,
                  risk_fraction: float = DEFAULT_RISK_FRACTION,
                  max_position_fraction: float = MAX_POSITION_FRACTION,
                  max_total_exposure_fraction: float = MAX_TOTAL_EXPOSURE_FRACTION,
                  direction: str = "long", fee_rate: float = DEFAULT_FEE_RATE,
                  slippage_rate: float = DEFAULT_SLIPPAGE_RATE) -> float:
    """Return notional constrained by net loss-at-stop (including costs) and exposure caps."""
    if (capital_usd <= 0 or stop_loss_pct <= 0 or risk_fraction <= 0
            or max_position_fraction <= 0 or max_total_exposure_fraction <= 0
            or direction not in ("long", "short") or fee_rate < 0 or slippage_rate < 0):
        return 0.0
    entry_fill = 1.0 + slippage_rate if direction == "long" else 1.0 - slippage_rate
    stop_price = entry_fill * (1.0 - stop_loss_pct / 100.0 if direction == "long"
                               else 1.0 + stop_loss_pct / 100.0)
    exit_fill = stop_price * (1.0 - slippage_rate if direction == "long"
                              else 1.0 + slippage_rate)
    exit_fee_fraction = (exit_fill / entry_fill) * fee_rate
    net_loss_fraction = ((1.0 - exit_fill / entry_fill + exit_fee_fraction + fee_rate)
                         if direction == "long"
                         else (exit_fill / entry_fill - 1.0 + exit_fee_fraction + fee_rate))
    if net_loss_fraction <= 0:
        return 0.0
    risk_budget = capital_usd * risk_fraction
    risk_limited_notional = risk_budget / net_loss_fraction
    per_position_cap = capital_usd * max_position_fraction
    total_room = max(0.0, capital_usd * max_total_exposure_fraction - open_exposure_usd)
    # Floor to cents so rounding can never push modeled stop loss above the risk budget.
    return floor(max(0.0, min(risk_limited_notional, per_position_cap, total_room)) * 100.0) / 100.0

def new_portfolio(starting_capital: float = STARTING_CAPITAL_USD) -> dict:
    return {"starting_capital": float(starting_capital), "cash": float(starting_capital), "open_positions": [], "closed_trades": []}


def ensure_position_ids(portfolio: dict) -> bool:
    """Assign stable IDs to legacy open positions; return whether state changed."""
    changed = False
    seen = set()
    for position in portfolio.get("open_positions", []):
        position_id = str(position.get("position_id") or "").strip()
        if not position_id or position_id in seen:
            position_id = str(uuid4())
            position["position_id"] = position_id
            changed = True
        seen.add(position_id)
    return changed


def _find_open_position(portfolio: dict, asset: str, position_id: Optional[str] = None):
    """Resolve a position exactly; never silently select among duplicate assets."""
    matches = [
        (index, position) for index, position in enumerate(portfolio.get("open_positions", []))
        if position.get("asset", "").upper() == asset.upper()
    ]
    if position_id is not None:
        matches = [(i, p) for i, p in matches if str(p.get("position_id", "")) == str(position_id)]
        if not matches:
            raise ValueError(f"No open paper position {position_id} for {asset}.")
        return matches[0]
    if not matches:
        raise ValueError(f"No open paper position for {asset}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple open positions for {asset}; position_id is required.")
    return matches[0]

def paper_entry(portfolio: dict, signal: Signal, stop_loss_pct: float, take_profit_pct: float = 20.0, direction: str = "long",
                fee_rate: float = DEFAULT_FEE_RATE, slippage_rate: float = DEFAULT_SLIPPAGE_RATE) -> dict:
    """Open a paper position only. No live order is ever sent."""
    check = evaluate_signal(signal)
    if not check["approved"]:
        raise ValueError("Signal rejected: " + "; ".join(check["reasons"]))
    if stop_loss_pct <= 0 or take_profit_pct <= 0:
        raise ValueError("Stop Loss and Take Profit percentages must be greater than zero.")
    direction = direction.lower()
    if direction not in ("long", "short"):
        raise ValueError("Direction must be long or short.")
    exposure = sum(p["notional_usd"] for p in portfolio["open_positions"])
    notional = size_position(portfolio["cash"], stop_loss_pct, exposure, direction=direction, fee_rate=fee_rate, slippage_rate=slippage_rate)
    if notional <= 0:
        raise ValueError("No available paper-trading risk budget or cash.")
    fill_price = signal.price_usd * (1.0 + slippage_rate if direction == "long" else 1.0 - slippage_rate)
    quantity = notional / fill_price
    entry_fee = notional * fee_rate
    if notional + entry_fee > portfolio["cash"]:
        raise ValueError("Insufficient virtual cash.")
    position = {
        "position_id": str(uuid4()),
        "asset": signal.asset, "market": signal.market, "direction": direction,
        "entry_reference_price": signal.price_usd, "entry_fill_price": fill_price,
        "quantity": quantity, "notional_usd": notional, "entry_fee_usd": entry_fee,
        "stop_loss_pct": stop_loss_pct,
        "stop_price": fill_price * (1.0 - stop_loss_pct / 100.0 if direction == "long" else 1.0 + stop_loss_pct / 100.0),
        "take_profit_pct": take_profit_pct,
        "take_profit_price": fill_price * (1.0 + take_profit_pct / 100.0 if direction == "long" else 1.0 - take_profit_pct / 100.0),
        "last_price_usd": signal.price_usd, "opened_at": datetime.now(timezone.utc).isoformat(),
        "source": signal.source,
    }
    position.update(position_risk_at_stop(position, fee_rate=fee_rate, slippage_rate=slippage_rate))
    position["risk_at_stop_pct_equity"] = position["risk_at_stop_usd"] / float(portfolio.get("starting_capital") or portfolio["cash"]) * 100.0
    portfolio["cash"] = round(portfolio["cash"] - notional - entry_fee, 8)
    portfolio["open_positions"].append(position)
    return position

def mark_position(position: dict, price_usd: float, fee_rate: float = DEFAULT_FEE_RATE,
                  slippage_rate: float = DEFAULT_SLIPPAGE_RATE) -> dict:
    if price_usd <= 0:
        raise ValueError("Mark price must be greater than zero.")
    is_short = position.get("direction", "long") == "short"
    exit_fill = price_usd * (1.0 + slippage_rate if is_short else 1.0 - slippage_rate)
    proceeds = position["quantity"] * exit_fill
    exit_fee = proceeds * fee_rate
    pnl = (position["notional_usd"] - proceeds - exit_fee - position["entry_fee_usd"]) if is_short else (proceeds - exit_fee - position["notional_usd"] - position["entry_fee_usd"])
    return {"mark_price_usd": price_usd, "estimated_exit_fill_usd": exit_fill, "unrealized_pnl_usd": pnl}

def paper_exit(portfolio: dict, asset: str, price_usd: float, reason: str = "manual",
               fee_rate: float = DEFAULT_FEE_RATE, slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
               position_id: Optional[str] = None) -> dict:
    """Close one exact paper position using conservative slippage and fees."""
    idx, position = _find_open_position(portfolio, asset, position_id)
    portfolio["open_positions"].pop(idx)
    is_short = position.get("direction", "long") == "short"
    exit_fill = price_usd * (1.0 + slippage_rate if is_short else 1.0 - slippage_rate)
    proceeds = position["quantity"] * exit_fill
    exit_fee = proceeds * fee_rate
    realized_pnl = (position["notional_usd"] - proceeds - exit_fee - position["entry_fee_usd"]) if is_short else (proceeds - exit_fee - position["notional_usd"] - position["entry_fee_usd"])
    portfolio["cash"] = round(portfolio["cash"] + (position["notional_usd"] + realized_pnl if is_short else proceeds - exit_fee), 8)
    trade = {
        **position, "exit_reference_price": price_usd, "exit_fill_price": exit_fill,
        "exit_fee_usd": exit_fee,
        "realized_pnl_usd": realized_pnl,
        "closed_at": datetime.now(timezone.utc).isoformat(), "exit_reason": reason,
    }
    portfolio["closed_trades"].append(trade)
    return trade

def portfolio_summary(portfolio: dict) -> dict:
    open_value = sum((p["notional_usd"] + mark_position(p, p["last_price_usd"])["unrealized_pnl_usd"] + p["entry_fee_usd"]) if p.get("direction", "long") == "short" else p["quantity"] * p["last_price_usd"] for p in portfolio["open_positions"])
    unrealized = sum(mark_position(p, p["last_price_usd"])["unrealized_pnl_usd"] for p in portfolio["open_positions"])
    realized = sum(t["realized_pnl_usd"] for t in portfolio["closed_trades"])
    equity = portfolio["cash"] + open_value
    open_exposure = sum(float(p.get("notional_usd", 0.0)) for p in portfolio["open_positions"])
    risk_total = 0.0
    risk_unknown = []
    for position in portfolio["open_positions"]:
        try:
            risk_total += position_risk_at_stop(position)["risk_at_stop_usd"]
        except (KeyError, TypeError, ValueError):
            risk_unknown.append(str(position.get("position_id") or position.get("asset") or "unknown"))
    return {
        "cash_usd": portfolio["cash"], "open_value_usd": open_value, "equity_usd": equity,
        "realized_pnl_usd": realized, "unrealized_pnl_usd": unrealized,
        "total_return_pct": (equity / portfolio["starting_capital"] - 1.0) * 100.0 if portfolio["starting_capital"] else 0.0,
        "open_positions": len(portfolio["open_positions"]), "closed_trades": len(portfolio["closed_trades"]),
        "open_exposure_usd": open_exposure,
        "open_exposure_pct_equity": open_exposure / equity * 100.0 if equity > 0 else None,
        "risk_at_stops_usd": None if risk_unknown else risk_total,
        "risk_at_stops_pct_equity": (risk_total / equity * 100.0) if not risk_unknown and equity > 0 else None,
        "risk_unknown_positions": risk_unknown,
    }


def update_position_mark(portfolio: dict, asset: str, price_usd: float,
                         position_id: Optional[str] = None) -> Optional[dict]:
    """Update one exact paper position and simulate stop/take-profit exits."""
    _, position = _find_open_position(portfolio, asset, position_id)
    if price_usd <= 0:
        raise ValueError("Mark price must be greater than zero.")

    # Backward compatibility: Supabase may contain positions created before
    # direction/take-profit fields were added.
    direction = str(position.get("direction", "long")).lower()
    is_short = direction == "short"
    position.setdefault("direction", direction)
    reference_entry = float(position.get("entry_fill_price") or position.get("entry_reference_price")
                             or position.get("entry_price_usd") or position.get("last_price_usd") or price_usd)
    stop_pct_raw = position.get("stop_loss_pct")
    take_profit_pct_raw = position.get("take_profit_pct")
    if not position.get("stop_price") and stop_pct_raw is None:
        raise ValueError("Legacy position has no stop price or stored stop percentage; refusing to invent risk.")
    if not position.get("take_profit_price") and take_profit_pct_raw is None:
        raise ValueError("Legacy position has no take-profit price or stored percentage; refusing to invent target.")
    stop_pct = float(stop_pct_raw) if stop_pct_raw is not None else None
    take_profit_pct = float(take_profit_pct_raw) if take_profit_pct_raw is not None else None
    if (stop_pct is not None and stop_pct <= 0) or (take_profit_pct is not None and take_profit_pct <= 0):
        raise ValueError("Legacy position has invalid stop/take-profit percentages.")
    if not position.get("stop_price"):
        position["stop_price"] = reference_entry * (1.0 + stop_pct / 100.0 if is_short else 1.0 - stop_pct / 100.0)
    if not position.get("take_profit_price"):
        position["take_profit_price"] = reference_entry * (1.0 - take_profit_pct / 100.0 if is_short else 1.0 + take_profit_pct / 100.0)

    position["last_price_usd"] = price_usd
    stop_hit = price_usd >= position["stop_price"] if is_short else price_usd <= position["stop_price"]
    take_profit_hit = price_usd <= position["take_profit_price"] if is_short else price_usd >= position["take_profit_price"]
    if stop_hit:
        return paper_exit(portfolio, asset, price_usd, reason="stop_loss", position_id=position.get("position_id"))
    if take_profit_hit:
        return paper_exit(portfolio, asset, price_usd, reason="take_profit", position_id=position.get("position_id"))
    return None


def update_position_from_candle(portfolio: dict, asset: str, high: float, low: float,
                                close: Optional[float] = None,
                                position_id: Optional[str] = None,
                                open: Optional[float] = None) -> Optional[dict]:
    """Check candle extremes; stop wins ambiguous bars and gaps fill at the open."""
    if high <= 0 or low <= 0 or high < low:
        raise ValueError("Invalid candle high/low.")
    if open is not None and (open <= 0 or not low <= open <= high):
        raise ValueError("Invalid candle open.")
    _, position = _find_open_position(portfolio, asset, position_id)
    direction = str(position.get("direction", "long")).lower()
    if direction not in ("long", "short"):
        raise ValueError("Invalid paper position direction.")
    short = direction == "short"
    position.setdefault("direction", direction)
    reference_entry = float(position.get("entry_fill_price") or position.get("entry_reference_price")
                            or position.get("entry_price_usd") or position.get("last_price_usd")
                            or (close if close is not None else open if open is not None else high))
    stop_pct_raw = position.get("stop_loss_pct")
    take_profit_pct_raw = position.get("take_profit_pct")
    if position.get("stop_price") is None and stop_pct_raw is None:
        raise ValueError("Legacy position has no stop price or stored stop percentage; refusing to invent risk.")
    if position.get("take_profit_price") is None and take_profit_pct_raw is None:
        raise ValueError("Legacy position has no take-profit price or stored percentage; refusing to invent target.")
    stop_pct = float(stop_pct_raw) if stop_pct_raw is not None else None
    take_profit_pct = float(take_profit_pct_raw) if take_profit_pct_raw is not None else None
    if (stop_pct is not None and stop_pct <= 0) or (take_profit_pct is not None and take_profit_pct <= 0):
        raise ValueError("Legacy position has invalid stop/take-profit percentages.")
    if position.get("stop_price") is None:
        position["stop_price"] = reference_entry * (1.0 + stop_pct / 100.0 if short else 1.0 - stop_pct / 100.0)
    if position.get("take_profit_price") is None:
        position["take_profit_price"] = reference_entry * (1.0 - take_profit_pct / 100.0 if short else 1.0 + take_profit_pct / 100.0)
    if close is not None:
        if close <= 0:
            raise ValueError("Candle close must be positive.")
        position["last_price_usd"] = float(close)
    stop_price, target_price = float(position["stop_price"]), float(position["take_profit_price"])
    stop_hit = high >= stop_price if short else low <= stop_price
    tp_hit = low <= target_price if short else high >= target_price
    if stop_hit:
        stop_fill = (max(stop_price, float(open)) if short and open is not None
                     else min(stop_price, float(open)) if not short and open is not None
                     else stop_price)
        return paper_exit(portfolio, asset, stop_fill, reason="stop_loss", position_id=position.get("position_id"))
    if tp_hit:
        return paper_exit(portfolio, asset, target_price, reason="take_profit", position_id=position.get("position_id"))
    return None
