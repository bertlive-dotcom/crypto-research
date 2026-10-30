"""Deterministic, simulation-only trading desk primitives.

No exchange execution, wallet signing, private keys, or external API calls live here.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

STARTING_CAPITAL_USD = 80.0
MAX_TOP10_HOLDER_PCT = 40.0
MAX_DEV_WALLET_PCT = 8.0
MIN_SOLANA_LIQUIDITY_USD = 30_000.0
MAX_GAIN_45M_PCT = 80.0
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
        if signal.gain_45m_pct is not None and signal.gain_45m_pct > MAX_GAIN_45M_PCT:
            reasons.append("Asset gained more than 80% in 45 minutes; reject late entry.")
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

def paper_entry(portfolio: dict, signal: Signal, stop_loss_pct: float,
                fee_rate: float = DEFAULT_FEE_RATE, slippage_rate: float = DEFAULT_SLIPPAGE_RATE) -> dict:
    """Open a paper position only. No live order is ever sent."""
    check = evaluate_signal(signal)
    if not check["approved"]:
        raise ValueError("Signal rejected: " + "; ".join(check["reasons"]))
    exposure = sum(p["notional_usd"] for p in portfolio["open_positions"])
    notional = size_position(portfolio["cash"], stop_loss_pct, exposure)
    if notional <= 0:
        raise ValueError("No available paper-trading risk budget or cash.")
    fill_price = signal.price_usd * (1.0 + slippage_rate)
    quantity = notional / fill_price
    entry_fee = notional * fee_rate
    if notional + entry_fee > portfolio["cash"]:
        raise ValueError("Insufficient virtual cash.")
    position = {
        "asset": signal.asset, "market": signal.market,
        "entry_reference_price": signal.price_usd, "entry_fill_price": fill_price,
        "quantity": quantity, "notional_usd": notional, "entry_fee_usd": entry_fee,
        "stop_loss_pct": stop_loss_pct, "stop_price": fill_price * (1.0 - stop_loss_pct / 100.0),
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
    exit_fill = price_usd * (1.0 - slippage_rate)
    proceeds = position["quantity"] * exit_fill
    exit_fee = proceeds * fee_rate
    pnl = proceeds - exit_fee - position["notional_usd"] - position["entry_fee_usd"]
    return {"mark_price_usd": price_usd, "estimated_exit_fill_usd": exit_fill, "unrealized_pnl_usd": pnl}

def paper_exit(portfolio: dict, asset: str, price_usd: float, reason: str = "manual",
               fee_rate: float = DEFAULT_FEE_RATE, slippage_rate: float = DEFAULT_SLIPPAGE_RATE) -> dict:
    """Close a paper position using conservative slippage and fees."""
    idx = next((i for i, p in enumerate(portfolio["open_positions"]) if p["asset"].upper() == asset.upper()), None)
    if idx is None:
        raise ValueError(f"No open paper position for {asset}.")
    position = portfolio["open_positions"].pop(idx)
    exit_fill = price_usd * (1.0 - slippage_rate)
    proceeds = position["quantity"] * exit_fill
    exit_fee = proceeds * fee_rate
    portfolio["cash"] = round(portfolio["cash"] + proceeds - exit_fee, 8)
    trade = {
        **position, "exit_reference_price": price_usd, "exit_fill_price": exit_fill,
        "exit_fee_usd": exit_fee,
        "realized_pnl_usd": proceeds - exit_fee - position["notional_usd"] - position["entry_fee_usd"],
        "closed_at": datetime.now(timezone.utc).isoformat(), "exit_reason": reason,
    }
    portfolio["closed_trades"].append(trade)
    return trade

def portfolio_summary(portfolio: dict) -> dict:
    open_value = sum(p["quantity"] * p["last_price_usd"] for p in portfolio["open_positions"])
    unrealized = sum(mark_position(p, p["last_price_usd"])["unrealized_pnl_usd"] for p in portfolio["open_positions"])
    realized = sum(t["realized_pnl_usd"] for t in portfolio["closed_trades"])
    equity = portfolio["cash"] + open_value
    return {
        "cash_usd": portfolio["cash"], "open_value_usd": open_value, "equity_usd": equity,
        "realized_pnl_usd": realized, "unrealized_pnl_usd": unrealized,
        "total_return_pct": (equity / portfolio["starting_capital"] - 1.0) * 100.0 if portfolio["starting_capital"] else 0.0,
        "open_positions": len(portfolio["open_positions"]), "closed_trades": len(portfolio["closed_trades"]),
    }


def update_position_mark(portfolio: dict, asset: str, price_usd: float) -> Optional[dict]:
    """Update a paper mark and simulate a stop exit if the observed price crosses it."""
    position = next((p for p in portfolio["open_positions"] if p["asset"].upper() == asset.upper()), None)
    if position is None:
        raise ValueError(f"No open paper position for {asset}.")
    position["last_price_usd"] = price_usd
    if price_usd <= position["stop_price"]:
        return paper_exit(portfolio, asset, price_usd, reason="stop_loss")
    return None
