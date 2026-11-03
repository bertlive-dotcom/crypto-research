"""Deterministic, simulation-only trading desk primitives.

No exchange execution, wallet signing, private keys, or external API calls live here.

Deployment sync marker: position-id migration support is included in this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
        major_gain = signal.gain_1h_pct
        # Backward compatibility for callers that still submit the old field.
        if major_gain is None:
            major_gain = signal.gain_45m_pct
        if major_gain is None:
            reasons.append("Missing 1-hour price change; major-asset signal rejected.")
        elif major_gain > MAX_MAJOR_GAIN_1H_PCT:
            reasons.append("Asset gained more than 80% in 1 hour; reject late entry.")
    else:
        reasons.append("Unknown market. Use 'solana' or 'major'.")
    return {"approved": not reasons, "reasons": reasons, "checks_passed": 0 if reasons else (6 if signal.market == "solana" else 2)}

def size_position(capital_usd: float, stop_loss_pct: float, open_exposure_usd: float = 0.0,
                  risk_fraction: float = DEFAULT_RISK_FRACTION,
                  max_position_fraction: float = MAX_POSITION_FRACTION,
                  max_total_exposure_fraction: float = MAX_TOTAL_EXPOSURE_FRACTION) -> float:
    """Return position notional constrained by per-trade risk and exposure caps."""
    if capital_usd <= 0 or stop_loss_pct <= 0:
        return 0.0
    risk_budget = capital_usd * risk_fraction
    risk_limited_notional = risk_budget / (stop_loss_pct / 100.0)
    per_position_cap = capital_usd * max_position_fraction
    total_room = max(0.0, capital_usd * max_total_exposure_fraction - open_exposure_usd)
    return round(max(0.0, min(risk_limited_notional, per_position_cap, total_room)), 2)

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
    notional = size_position(portfolio["cash"], stop_loss_pct, exposure)
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
               position_id: Optional[str] = None, quantity: Optional[float] = None,
               fraction: Optional[float] = None) -> dict:
    """Close all or part of one exact paper position; fees and entry basis are allocated pro rata."""
    idx, position = _find_open_position(portfolio, asset, position_id)
    if price_usd <= 0:
        raise ValueError("Exit price must be greater than zero.")
    if quantity is not None and fraction is not None:
        raise ValueError("Specify quantity or fraction, not both.")
    original_quantity = float(position["quantity"])
    if fraction is not None:
        if not 0 < float(fraction) <= 1:
            raise ValueError("Close fraction must be greater than zero and at most one.")
        close_quantity = original_quantity * float(fraction)
    elif quantity is not None:
        close_quantity = float(quantity)
        if close_quantity <= 0 or close_quantity > original_quantity:
            raise ValueError("Close quantity must be greater than zero and no greater than the open quantity.")
    else:
        close_quantity = original_quantity

    close_ratio = close_quantity / original_quantity
    closed_notional = float(position["notional_usd"]) * close_ratio
    allocated_entry_fee = float(position.get("entry_fee_usd", 0.0)) * close_ratio
    is_short = position.get("direction", "long") == "short"
    exit_fill = price_usd * (1.0 + slippage_rate if is_short else 1.0 - slippage_rate)
    proceeds = close_quantity * exit_fill
    exit_fee = proceeds * fee_rate
    realized_pnl = (
        closed_notional - proceeds - exit_fee - allocated_entry_fee
        if is_short else proceeds - exit_fee - closed_notional - allocated_entry_fee
    )

    # Short collateral is released together with P&L and the already-paid entry fee.
    cash_credit = closed_notional + realized_pnl + allocated_entry_fee if is_short else proceeds - exit_fee
    portfolio["cash"] = round(portfolio["cash"] + cash_credit, 8)

    remaining_quantity = original_quantity - close_quantity
    fully_closed = remaining_quantity <= max(1e-12, original_quantity * 1e-12)
    trade = {
        **position,
        "quantity": close_quantity,
        "notional_usd": closed_notional,
        "entry_fee_usd": allocated_entry_fee,
        "exit_reference_price": price_usd,
        "exit_fill_price": exit_fill,
        "exit_fee_usd": exit_fee,
        "realized_pnl_usd": realized_pnl,
        "closed_quantity": close_quantity,
        "remaining_quantity": 0.0 if fully_closed else remaining_quantity,
        "closed_fraction": close_ratio,
        "is_partial": not fully_closed,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "exit_reason": reason,
    }
    portfolio["closed_trades"].append(trade)

    if fully_closed:
        portfolio["open_positions"].pop(idx)
    else:
        position["quantity"] = remaining_quantity
        position["notional_usd"] = round(float(position["notional_usd"]) - closed_notional, 12)
        position["entry_fee_usd"] = round(float(position.get("entry_fee_usd", 0.0)) - allocated_entry_fee, 12)
    return trade

def portfolio_summary(portfolio: dict) -> dict:
    """Mark portfolio to conservative net liquidation value, including estimated exit costs."""
    open_value = 0.0
    unrealized = 0.0
    for position in portfolio.get("open_positions", []):
        mark = mark_position(position, float(position.get("last_price_usd") or position["entry_fill_price"]))
        unrealized += mark["unrealized_pnl_usd"]
        if position.get("direction", "long") == "short":
            open_value += float(position["notional_usd"]) + mark["unrealized_pnl_usd"] + float(position.get("entry_fee_usd", 0.0))
        else:
            open_value += float(position["quantity"]) * float(mark["estimated_exit_fill_usd"]) - (
                float(position["quantity"]) * float(mark["estimated_exit_fill_usd"]) * DEFAULT_FEE_RATE
            )
    realized = sum(float(t.get("realized_pnl_usd", 0.0)) for t in portfolio.get("closed_trades", []))
    equity = float(portfolio["cash"]) + open_value
    return {
        "cash_usd": portfolio["cash"], "open_value_usd": open_value, "equity_usd": equity,
        "realized_pnl_usd": realized, "unrealized_pnl_usd": unrealized,
        "total_return_pct": (equity / portfolio["starting_capital"] - 1.0) * 100.0 if portfolio["starting_capital"] else 0.0,
        "open_positions": len(portfolio.get("open_positions", [])), "closed_trades": len(portfolio.get("closed_trades", [])),
    }


def ensure_daily_equity_baseline(portfolio: dict, now: Optional[datetime] = None,
                                 timezone_name: str = "Europe/Madrid") -> dict:
    """Persist the start-of-day equity snapshot; reset only when the local trading date changes."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    local_now = reference.astimezone(ZoneInfo(timezone_name))
    day_key = local_now.date().isoformat()
    risk = portfolio.setdefault("daily_risk", {})
    if risk.get("date") != day_key or risk.get("timezone") != timezone_name or not risk.get("start_equity_usd"):
        equity = portfolio_summary(portfolio)["equity_usd"]
        risk.update({
            "date": day_key,
            "timezone": timezone_name,
            "start_equity_usd": round(float(equity), 8),
            "baseline_at": local_now.isoformat(),
        })
    return risk


def daily_equity_drawdown(portfolio: dict, now: Optional[datetime] = None,
                          timezone_name: str = "Europe/Madrid") -> dict:
    """Return daily equity change from the persisted local-day opening snapshot."""
    risk = ensure_daily_equity_baseline(portfolio, now=now, timezone_name=timezone_name)
    current_equity = float(portfolio_summary(portfolio)["equity_usd"])
    start_equity = float(risk["start_equity_usd"])
    change = current_equity - start_equity
    loss = max(0.0, -change)
    return {
        "date": risk["date"],
        "timezone": risk["timezone"],
        "start_equity_usd": start_equity,
        "current_equity_usd": current_equity,
        "change_usd": change,
        "loss_usd": loss,
        "loss_pct": (loss / start_equity * 100.0) if start_equity > 0 else 0.0,
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
    stop_pct = float(position.get("stop_loss_pct", 10.0))
    take_profit_pct = float(position.get("take_profit_pct", 20.0))
    if not position.get("stop_price"):
        position["stop_price"] = reference_entry * (1.0 + stop_pct / 100.0 if is_short else 1.0 - stop_pct / 100.0)
    if not position.get("take_profit_price"):
        position["take_profit_price"] = reference_entry * (1.0 - take_profit_pct / 100.0 if is_short else 1.0 + take_profit_pct / 100.0)
    position.setdefault("take_profit_pct", take_profit_pct)
    position.setdefault("stop_loss_pct", stop_pct)

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
                                position_id: Optional[str] = None) -> Optional[dict]:
    """Check candle extremes against one exact position; stop wins if both levels cross."""
    if high <= 0 or low <= 0 or high < low:
        raise ValueError("Invalid candle high/low.")
    _, position = _find_open_position(portfolio, asset, position_id)
    if close is not None:
        if close <= 0:
            raise ValueError("Candle close must be positive.")
        position["last_price_usd"] = float(close)
    short = position.get("direction", "long") == "short"
    stop_hit = high >= float(position["stop_price"]) if short else low <= float(position["stop_price"])
    tp_hit = low <= float(position["take_profit_price"]) if short else high >= float(position["take_profit_price"])
    if stop_hit:
        return paper_exit(portfolio, asset, float(position["stop_price"]), reason="stop_loss", position_id=position.get("position_id"))
    if tp_hit:
        return paper_exit(portfolio, asset, float(position["take_profit_price"]), reason="take_profit", position_id=position.get("position_id"))
    return None
