"""Current research snapshot: BTC-relative forecasts and Black-Litterman weights."""
from __future__ import annotations
import numpy as np
from portfolio_engine.analytics.black_litterman import posterior_expected_returns
from portfolio_engine.analytics.covariance import estimate_covariance
from portfolio_engine.analytics.market_equilibrium import market_cap_weights, market_equilibrium_returns
from portfolio_engine.analytics.portfolio import optimize_long_only
from portfolio_engine.analytics.returns import simple_returns
from portfolio_engine.data.coingecko_history import fetch_watchlist_history
from portfolio_engine.forecast.model import forecast_latest


def align_common_history(series: dict, symbols: list[str], min_observations: int = 120) -> tuple[list[str], np.ndarray, list[str]]:
    """Return a common-date close matrix and assets with adequate contiguous history."""
    available = [symbol for symbol in symbols if symbol in series]
    if not available:
        raise ValueError("no assets have historical price data")
    date_sets = [set(series[symbol]["dates"]) for symbol in available]
    common_dates = sorted(set.intersection(*date_sets))
    if len(common_dates) < min_observations:
        raise ValueError("common aligned history is below the minimum observation count")
    matrix = np.asarray([
        [dict(zip(series[symbol]["dates"], series[symbol]["closes"]))[date]
         for symbol in available]
        for date in common_dates
    ], dtype=float)
    if not np.isfinite(matrix).all() or (matrix <= 0).any():
        raise ValueError("aligned prices must be finite and positive")
    return common_dates, matrix, available


def build_portfolio_snapshot(*, history: dict | None = None, symbols: list[str] | None = None,
                              horizon: int = 7, min_history: int = 120,
                              min_train_samples: int = 30, min_validation_samples: int = 20,
                              shrinkage: float = 0.25, tau: float = 0.05,
                              risk_aversion: float = 2.5, max_weight: float = 0.35) -> dict:
    """Build a current as-of research allocation; no execution or persistence."""
    history = history or fetch_watchlist_history(symbols=symbols)
    requested = list(symbols or history["series"].keys())
    if "BTCUSD" not in history["series"]:
        raise ValueError("BTC history is required as the relative-strength benchmark")
    dates, prices, aligned_symbols = align_common_history(
        history["series"], requested, min_observations=min_history
    )
    if "BTCUSD" not in aligned_symbols:
        raise ValueError("BTC must be present in the common aligned history")
    btc_index = aligned_symbols.index("BTCUSD")
    btc_prices = prices[:, btc_index]
    forecasts, rejected = {}, []
    for index, symbol in enumerate(aligned_symbols):
        if symbol == "BTCUSD":
            # BTC is its own benchmark; zero relative-strength features by definition.
            benchmark = None
        else:
            benchmark = btc_prices
        try:
            result = forecast_latest(
                prices[:, index], horizon=horizon, min_train_samples=min_train_samples,
                min_validation_samples=min_validation_samples, benchmark_prices=benchmark,
            )
            forecasts[symbol] = result
            if not result["view_eligible"]:
                rejected.append({"symbol": symbol, "reason": "forecast_not_view_eligible",
                                 "mae_skill_vs_zero": result["mae_skill_vs_zero"],
                                 "validation_count": result["walk_forward_validation_count"]})
        except (ValueError, ArithmeticError) as exc:
            rejected.append({"symbol": symbol, "reason": "forecast_failed", "detail": str(exc)})

    eligible = [symbol for symbol in aligned_symbols
                if symbol in forecasts and forecasts[symbol]["view_eligible"]]
    if len(eligible) < 3:
        return {
            "status": "insufficient_eligible_assets", "source": history.get("source"),
            "observed_at": history.get("observed_at"), "dates": dates,
            "forecasts": forecasts, "rejected": rejected,
            "eligible_assets": eligible, "portfolio": None,
            "reason": "At least three independently validated asset views are required.",
        }
    missing_caps = [symbol for symbol in eligible if symbol not in history.get("market_caps", {})]
    if missing_caps:
        raise ValueError(f"missing current market caps for eligible assets: {missing_caps}")

    columns = [aligned_symbols.index(symbol) for symbol in eligible]
    selected_prices = prices[:, columns]
    daily_returns = simple_returns(selected_prices)
    horizon_covariance = estimate_covariance(
        daily_returns, shrinkage=shrinkage, annualization=float(horizon)
    )
    caps = {symbol: history["market_caps"][symbol] for symbol in eligible}
    equilibrium_weights = market_cap_weights(caps, eligible)
    prior = market_equilibrium_returns(horizon_covariance, equilibrium_weights, risk_aversion)
    views = np.asarray([forecasts[symbol]["forecast_return"] for symbol in eligible], dtype=float)
    errors = np.asarray([forecasts[symbol]["absolute_error_q90"] for symbol in eligible], dtype=float)
    if not np.isfinite(errors).all() or (errors <= 0).any():
        raise ValueError("all eligible forecasts must have positive calibrated uncertainty")
    pick = np.eye(len(eligible))
    omega = np.diag(np.maximum(errors ** 2, 1e-8))
    posterior = posterior_expected_returns(
        horizon_covariance, prior, pick, views, omega, tau=tau
    )
    optimized = optimize_long_only(
        posterior, horizon_covariance, risk_aversion=risk_aversion, max_weight=max_weight
    )
    allocations = [
        {"symbol": symbol, "market_cap_weight": float(equilibrium_weights[i]),
         "forecast_return": float(views[i]), "posterior_return": float(posterior[i]),
         "weight": float(optimized["weights"][i]),
         "forecast_mae_skill": forecasts[symbol]["mae_skill_vs_zero"],
         "relative_strength_7d_vs_btc": None if symbol == "BTCUSD" else float(
             (selected_prices[-1, i] / selected_prices[-8, i] - 1.0)
             - (btc_prices[-1] / btc_prices[-8] - 1.0)),
         "relative_strength_30d_vs_btc": None if symbol == "BTCUSD" else float(
             (selected_prices[-1, i] / selected_prices[-31, i] - 1.0)
             - (btc_prices[-1] / btc_prices[-31] - 1.0)),
        } for i, symbol in enumerate(eligible)
    ]
    return {
        "status": "research_only", "source": history.get("source"),
        "quote_currency": history.get("quote_currency", "USD"),
        "observed_at": history.get("observed_at"), "history_start": dates[0],
        "history_end": dates[-1], "history_observations": len(dates),
        "horizon_days": horizon, "eligible_assets": eligible,
        "allocations": allocations, "rejected": rejected,
        "portfolio": {
            "expected_return_horizon": optimized["expected_return"],
            "volatility_horizon": optimized["volatility"],
            "objective": optimized["objective"], "converged": optimized["converged"],
            "iterations": optimized["iterations"], "max_weight": max_weight,
            "risk_aversion": risk_aversion,
        },
        "method": {
            "prior": "market_cap_weighted_equilibrium",
            "views": "only walk_forward_eligible_forecast_returns",
            "view_uncertainty": "diagonal_squared_90th_percentile_absolute_walk_forward_error",
            "covariance": "daily_sample_covariance_with_diagonal_shrinkage_scaled_by_horizon",
            "optimizer": "long_only_capped_simplex_mean_variance",
            "relative_strength": "7d_and_30d_excess_return_vs_BTC_in_forecast_features",
            "market_caps": "current_snapshot_only_not_a_historical_backtest_input",
        },
        "read_only": True, "paper_only": True,
    }
