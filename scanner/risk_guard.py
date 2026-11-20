"""Portfolio-level risk guard for the Market Scanner paper account.

All limits are measured against the initial virtual capital. This module only
blocks new paper entries; existing positions continue to be marked and their
configured stop-loss/take-profit rules remain active.
"""
from __future__ import annotations

from datetime import datetime, timezone

from trading_desk import mark_position, portfolio_summary


def evaluate_risk_guard(
    portfolio: dict,
    now: datetime | None = None,
    daily_loss_pct: float = 2.0,
    trailing_drawdown_pct: float = 6.0,
    floating_loss_pct: float = 2.0,
) -> dict:
    """Update persistent risk state and report whether new entries are allowed.

    Daily loss is measured from UTC day-start equity and is latched until the
    next UTC day. Trailing drawdown is measured from the highest observed
    portfolio equity and is permanently latched once breached. Floating loss
    is the sum of estimated unrealized P&L, including simulated exit costs.
    """
    if min(daily_loss_pct, trailing_drawdown_pct, floating_loss_pct) <= 0:
        raise ValueError("Risk limits must be greater than zero.")

    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    observed_at = observed_at.astimezone(timezone.utc)
    utc_day = observed_at.date().isoformat()

    starting_capital = float(portfolio.get("starting_capital") or 0.0)
    if starting_capital <= 0:
        raise ValueError("Portfolio starting capital must be greater than zero.")

    equity = float(portfolio_summary(portfolio)["equity_usd"])
    state = portfolio.setdefault("risk_guard", {})

    if state.get("utc_day") != utc_day:
        state["utc_day"] = utc_day
        state["day_start_equity_usd"] = equity

    day_start_equity = float(state.get("day_start_equity_usd", equity))
    high_water = float(state.get("high_water_equity_usd", equity))
    high_water = max(high_water, equity)
    state["high_water_equity_usd"] = high_water

    floating_pnl = sum(
        float(mark_position(position, float(position["last_price_usd"]))["unrealized_pnl_usd"])
        for position in portfolio.get("open_positions", [])
    )
    daily_pnl = equity - day_start_equity
    drawdown = max(0.0, high_water - equity)
    floating_loss = max(0.0, -floating_pnl)

    daily_limit = starting_capital * daily_loss_pct / 100.0
    drawdown_limit = starting_capital * trailing_drawdown_pct / 100.0
    floating_limit = starting_capital * floating_loss_pct / 100.0

    if daily_pnl <= -daily_limit:
        state["daily_loss_breached_date"] = utc_day
    if drawdown >= drawdown_limit:
        state["max_drawdown_breached"] = True

    reasons = []
    if state.get("daily_loss_breached_date") == utc_day:
        reasons.append("Daily loss limit breached; new entries blocked until the next UTC day.")
    if state.get("max_drawdown_breached"):
        reasons.append("Trailing maximum drawdown breached; paper account remains halted.")
    if floating_loss >= floating_limit:
        reasons.append("Aggregate floating-loss limit breached; new entries blocked.")

    state["last_checked_at"] = observed_at.isoformat()
    state["last_equity_usd"] = equity
    state["last_daily_pnl_usd"] = daily_pnl
    state["last_floating_pnl_usd"] = floating_pnl

    return {
        "can_open_new_positions": not reasons,
        "blocked_reasons": reasons,
        "equity_usd": round(equity, 8),
        "day_start_equity_usd": round(day_start_equity, 8),
        "high_water_equity_usd": round(high_water, 8),
        "daily_pnl_usd": round(daily_pnl, 8),
        "daily_loss_limit_usd": round(daily_limit, 8),
        "drawdown_usd": round(drawdown, 8),
        "trailing_drawdown_limit_usd": round(drawdown_limit, 8),
        "floating_pnl_usd": round(floating_pnl, 8),
        "floating_loss_limit_usd": round(floating_limit, 8),
        "utc_day": utc_day,
    }
