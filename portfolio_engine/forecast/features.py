"""Causal technical and BTC-relative features at each forecast origin."""
from __future__ import annotations
import numpy as np

FEATURE_NAMES = (
    "rsi_14_scaled", "momentum_7d", "momentum_30d", "volatility_20d",
    "trend_vs_sma20", "macd_histogram_scaled",
    "relative_momentum_7d_vs_btc", "relative_momentum_30d_vs_btc",
)
MIN_FEATURE_HISTORY = 40


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1.0)
    output = np.empty(values.size, dtype=float)
    output[0] = values[0]
    for index in range(1, values.size):
        output[index] = alpha * values[index] + (1.0 - alpha) * output[index - 1]
    return output


def technical_features(prices: object, index: int, benchmark_prices: object | None = None) -> np.ndarray:
    """Return one causal feature row; benchmark series, when supplied, is BTC."""
    values = np.asarray(prices, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("prices must be a finite, positive 1D series")
    if index < MIN_FEATURE_HISTORY - 1 or index >= values.size:
        raise ValueError("index does not have sufficient in-range history")
    history = values[:index + 1]
    changes = np.diff(history[-15:])
    gains, losses = np.maximum(changes, 0.0), np.maximum(-changes, 0.0)
    avg_gain, avg_loss = float(gains.mean()), float(losses.mean())
    rsi = (100.0 if avg_gain > 0 else 50.0) if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    trailing = history[-21:]
    returns = trailing[1:] / trailing[:-1] - 1.0
    volatility = float(np.std(returns, ddof=1))
    sma20 = float(history[-20:].mean())
    macd = _ema(history, 12) - _ema(history, 26)
    signal = _ema(macd[25:], 9)
    histogram = float(macd[-1] - signal[-1])

    relative_7d = relative_30d = 0.0
    if benchmark_prices is not None:
        benchmark = np.asarray(benchmark_prices, dtype=float)
        if benchmark.ndim != 1 or benchmark.size != values.size:
            raise ValueError("benchmark_prices must be a 1D series aligned to prices")
        if not np.isfinite(benchmark).all() or (benchmark <= 0).any():
            raise ValueError("benchmark_prices must be finite and strictly positive")
        benchmark_history = benchmark[:index + 1]
        relative_7d = (history[-1] / history[-8] - 1.0) - (benchmark_history[-1] / benchmark_history[-8] - 1.0)
        relative_30d = (history[-1] / history[-31] - 1.0) - (benchmark_history[-1] / benchmark_history[-31] - 1.0)

    row = np.asarray([
        (rsi - 50.0) / 50.0,
        history[-1] / history[-8] - 1.0,
        history[-1] / history[-31] - 1.0,
        volatility,
        history[-1] / sma20 - 1.0,
        histogram / history[-1],
        relative_7d,
        relative_30d,
    ], dtype=float)
    if not np.isfinite(row).all():
        raise ValueError("technical feature row contains non-finite values")
    return row
