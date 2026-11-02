from datetime import datetime, timedelta, timezone

import pytest

from tools.run_breakout_retest_research import evaluate


def _candles(count=260):
    rows = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    for i in range(count):
        # Smooth rising history; deterministic, valid OHLC and closed candles.
        open_price = price
        close = price * 1.001
        rows.append({
            "open": open_price,
            "high": close * 1.002,
            "low": open_price * 0.998,
            "close": close,
            "volume": 1000.0,
            "date": (start + timedelta(days=i)).date().isoformat(),
            "_close_time": start + timedelta(days=i + 1),
        })
        price = close
    return rows


def test_retest_research_returns_separate_exploration_and_holdout():
    result = evaluate(_candles())
    assert result["method"] == "daily_breakout_retest_next_open"
    assert "exploration" in result
    assert "holdout" in result
    assert result["exploration"]["sample_status"] == "small_sample"
    assert result["holdout"]["sample_status"] == "small_sample"
    assert result["limitations"]


def test_retest_window_must_be_positive():
    with pytest.raises(ValueError):
        evaluate(_candles(), retest_window=0)
