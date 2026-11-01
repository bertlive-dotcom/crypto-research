import unittest
from datetime import datetime, timedelta, timezone

from global_markets.market_analysis import analyze_candles, analyze_feed, classify_timeframe_structure


class MarketAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    def rows(self, count=60, interval="1d", close_time=None):
        rows = []
        end = close_time or self.now - timedelta(minutes=1)
        step = timedelta(hours=4) if interval == "4h" else timedelta(days=1)
        for i in range(count):
            close = 100 + i * 0.5
            timestamp = end - step * (count - 1 - i)
            rows.append({
                "symbol": "BTCUSDT", "interval": interval, "source": "binance",
                "timestamp": (timestamp - step).isoformat(),
                "close_timestamp": timestamp.isoformat(),
                "open": close - 0.2, "high": close + 0.5,
                "low": close - 0.5, "close": close, "volume": 10.0,
            })
        return rows

    def test_fresh_daily_series_has_indicators_and_technical_score(self):
        result = analyze_candles(self.rows(), now=self.now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["status"], "fresh")
        self.assertIsNotNone(result["indicators"]["rsi_14"])
        self.assertIsNotNone(result["indicators"]["macd_12_26"])
        self.assertIsNotNone(result["indicators"]["macd_histogram"])
        self.assertIsNotNone(result["indicators"]["macd_histogram_change"])
        self.assertIsNotNone(result["indicators"]["sma_20"])
        self.assertEqual(result["score_type"], "technical_only_not_investment_recommendation")

    def test_daily_risk_metrics_require_sufficient_history(self):
        result = analyze_candles(self.rows(count=61), now=self.now)
        metrics = result["risk_metrics"]
        self.assertIsNotNone(metrics["return_20d_pct"])
        self.assertIsNotNone(metrics["return_60d_pct"])
        self.assertIsNone(metrics["return_120d_pct"])
        self.assertIsNotNone(metrics["realized_volatility_20d_pct_annualized"])
        self.assertIsNotNone(metrics["realized_volatility_60d_pct_annualized"])
        self.assertEqual(metrics["drawdown_window_bars"], 61)
        self.assertEqual(metrics["max_drawdown_120d_pct"], 0.0)

    def test_drawdown_measures_peak_to_trough_loss(self):
        rows = self.rows(count=60)
        for index, row in enumerate(rows):
            close = 150.0 if index < 30 else 75.0 + (index - 30) * 0.5
            row["close"] = close
            row["high"] = close + 1
            row["low"] = close - 1
        result = analyze_candles(rows, now=self.now)
        self.assertEqual(result["risk_metrics"]["max_drawdown_120d_pct"], -50.0)

    def test_rejects_stale_xmr_like_history(self):
        old = self.rows(close_time=self.now - timedelta(days=30))
        result = analyze_candles(old, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("stale_market_data", result["reasons"])

    def test_rejects_insufficient_history(self):
        result = analyze_candles(self.rows(count=10), now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("insufficient_history", result["reasons"])

    def test_rejects_future_open_time(self):
        future = self.rows(close_time=self.now + timedelta(hours=2))
        future[-1]["timestamp"] = (self.now + timedelta(hours=1)).isoformat()
        result = analyze_candles(future, now=self.now)
        self.assertFalse(result["eligible"])
        self.assertIn("future_candle", result["reasons"])

    def test_ignores_current_unclosed_daily_candle(self):
        rows = self.rows()
        rows.append({
            "symbol": "BTCUSDT", "interval": "1d", "source": "binance",
            "timestamp": (self.now + timedelta(seconds=1)).isoformat(),
            "close_timestamp": (self.now + timedelta(days=1)).isoformat(),
            "open": 100.0, "high": 10000.0, "low": 90.0,
            "close": 9999.0, "volume": 1000.0,
        })
        result = analyze_candles(rows, now=self.now)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["bars"], 60)
        self.assertEqual(result["latest_close"], 129.5)

    def test_risk_adjusted_ranking_requires_complete_history_and_uses_120d(self):
        from global_markets.market_analysis import build_risk_adjusted_relative_strength
        rows = []
        for symbol, rs20, rs60, rs120, vol, dd in [
            ("AAAUSDT", 20, 30, 40, 30, -10),
            ("BBBUSDT", -10, -5, -2, 90, -40),
            ("HYPEUSDT", 10, None, None, 60, -20),
            ("BTCUSDT", 0, 0, 0, 20, -5),
        ]:
            rows.append({
                "symbol": symbol,
                "relative_strength_vs_btc_20d_pp": rs20,
                "relative_strength_vs_btc_60d_pp": rs60,
                "relative_strength_vs_btc_120d_pp": rs120,
                "risk_metrics": {
                    "realized_volatility_20d_pct_annualized": vol,
                    "max_drawdown_120d_pct": dd,
                },
            })
        ranked, coverage = build_risk_adjusted_relative_strength(rows)
        self.assertEqual([row["symbol"] for row in ranked], ["AAAUSDT", "BBBUSDT"])
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])
        self.assertEqual(ranked[0]["relative_strength_120d_pp"], 40)
        hype = next(row for row in coverage if row["symbol"] == "HYPEUSDT")
        self.assertEqual(hype["data_quality_pct"], 60.0)
        self.assertEqual(hype["ranking_status"], "insufficient_history")
    def test_risk_adjusted_ranking_excludes_nan_and_infinite_metrics(self):
        from global_markets.market_analysis import build_risk_adjusted_relative_strength
        rows = [{
            "symbol": "AAAUSDT",
            "relative_strength_vs_btc_20d_pp": 1.0,
            "relative_strength_vs_btc_60d_pp": 2.0,
            "relative_strength_vs_btc_120d_pp": 3.0,
            "risk_metrics": {
                "realized_volatility_20d_pct_annualized": float("nan"),
                "max_drawdown_120d_pct": -10.0,
            },
        }, {
            "symbol": "BBBUSDT",
            "relative_strength_vs_btc_20d_pp": 1.0,
            "relative_strength_vs_btc_60d_pp": 2.0,
            "relative_strength_vs_btc_120d_pp": 3.0,
            "risk_metrics": {
                "realized_volatility_20d_pct_annualized": 20.0,
                "max_drawdown_120d_pct": float("-inf"),
            },
        }]
        ranked, coverage = build_risk_adjusted_relative_strength(rows)
        self.assertEqual(ranked, [])
        self.assertTrue(all(row["data_quality_pct"] == 80.0 for row in coverage))


    def test_feed_analysis_exposes_empty_ranking_when_only_benchmark_exists(self):
        daily = self.rows(count=130, interval="1d")
        tactical = self.rows(count=60, interval="4h")
        result = analyze_feed({
            "source": "binance", "data": daily + tactical, "unavailable": [],
        }, now=self.now)
        self.assertIn("risk_adjusted_relative_strength", result)
        self.assertEqual(result["risk_adjusted_relative_strength"], [])
        self.assertEqual(result["risk_adjusted_relative_strength_coverage"], [])

    def test_feed_analysis_keeps_provider_unavailable_pairs(self):
        result = analyze_feed({
            "source": "binance", "data": self.rows(),
            "unavailable": [{"symbol": "LEOUSD", "reason": "not_listed"}],
        }, now=self.now)
        self.assertEqual(result["eligible_series"], 1)
        self.assertEqual(result["provider_unavailable"][0]["symbol"], "LEOUSD")

    def test_feed_analysis_builds_alignment_only_with_both_fresh_timeframes(self):
        daily = self.rows(interval="1d")
        tactical = self.rows(interval="4h")
        result = analyze_feed({
            "source": "binance", "data": daily + tactical, "unavailable": [],
        }, now=self.now)
        self.assertEqual(len(result["cross_timeframe"]), 1)
        alignment = result["cross_timeframe"][0]
        self.assertEqual(alignment["symbol"], "BTCUSDT")
        self.assertEqual(alignment["alignment_score"], round(alignment["daily_score"] * 0.60 + alignment["4h_score"] * 0.40, 1))
        self.assertIn(alignment["stance"], {"bullish_alignment", "bearish_alignment", "mixed_or_neutral"})
        self.assertIn(alignment["rsi_macd_confirmation"], {"confirmed_both", "daily_only", "4h_only", "not_confirmed"})

    def test_feed_analysis_does_not_infer_alignment_when_interval_missing(self):
        result = analyze_feed({
            "source": "binance", "data": self.rows(interval="1d"), "unavailable": [],
        }, now=self.now)
        self.assertEqual(result["cross_timeframe"], [])

    def test_classifies_daily_strength_without_4h_confirmation_as_divergence(self):
        daily = {"eligible": True, "technical_screen_score": 100, "indicators": {}}
        tactical = {"eligible": True, "technical_screen_score": 37.5, "indicators": {}}
        result = classify_timeframe_structure(daily, tactical)
        self.assertEqual(result["category"], "timeframe_divergence")

    def test_classifies_weak_daily_with_strong_4h_as_possible_reversal(self):
        daily = {"eligible": True, "technical_screen_score": 12.5, "indicators": {}}
        tactical = {"eligible": True, "technical_screen_score": 75,
                    "indicators": {"macd_12_26": 2.0, "macd_signal_9": 1.0, "rsi_14": 54}}
        result = classify_timeframe_structure(daily, tactical)
        self.assertEqual(result["category"], "possible_reversal")
        self.assertIn("la tendència diària continua feble", result["explanation"])

    def test_classifies_weakness_when_both_timeframes_are_weak(self):
        daily = {"eligible": True, "technical_screen_score": 0, "indicators": {}}
        tactical = {"eligible": True, "technical_screen_score": 25, "indicators": {}}
        self.assertEqual(classify_timeframe_structure(daily, tactical)["category"], "weakness")

    def test_requires_both_fresh_timeframes_for_structure(self):
        daily = {"eligible": True, "technical_screen_score": 80, "indicators": {}}
        self.assertEqual(classify_timeframe_structure(daily, None)["category"], "insufficient_timeframes")


    def test_recovery_without_rsi_confirmation_is_only_incipient(self):
        daily = {"eligible": True, "technical_screen_score": 12.5, "indicators": {}}
        tactical = {"eligible": True, "technical_screen_score": 75,
                    "indicators": {"macd_12_26": 2.0, "macd_signal_9": 1.0, "rsi_14": 48}}
        self.assertEqual(classify_timeframe_structure(daily, tactical)["category"], "incipient_recovery")

    def test_confirmed_trend_requires_rsi_and_macd_on_both_frames(self):
        daily = {"eligible": True, "technical_screen_score": 75,
                 "indicators": {"rsi_14": 58, "macd_12_26": 2, "macd_signal_9": 1}}
        tactical = {"eligible": True, "technical_screen_score": 75,
                    "indicators": {"rsi_14": 55, "macd_12_26": 2, "macd_signal_9": 1}}
        self.assertEqual(classify_timeframe_structure(daily, tactical)["category"], "confirmed_trend")

    def test_entry_classification_detects_confirmed_trend(self):
        from global_markets.market_analysis import classify_entry_opportunity
        daily = {"eligible": True, "latest_close": 105, "indicators": {
            "sma_20": 100, "rsi_14": 58, "macd_histogram": 1}}
        tactical = {"eligible": True, "latest_close": 102, "indicators": {
            "sma_20": 100, "rsi_14": 55, "macd_histogram": 0.5}}
        result = classify_entry_opportunity(daily, tactical, {"category": "confirmed_trend"})
        self.assertEqual(result["category"], "confirmed_entry_setup")
        self.assertEqual(result["quality_score"], 100)

    def test_entry_classification_flags_late_entry_risk(self):
        from global_markets.market_analysis import classify_entry_opportunity
        daily = {"eligible": True, "latest_close": 112, "indicators": {
            "sma_20": 100, "rsi_14": 72, "macd_histogram": 1}}
        tactical = {"eligible": True, "latest_close": 110, "indicators": {
            "sma_20": 100, "rsi_14": 76, "macd_histogram": 1}}
        result = classify_entry_opportunity(daily, tactical, {"category": "confirmed_trend"})
        self.assertEqual(result["category"], "late_entry_risk")
        self.assertTrue(any("RSI elevat" in reason for reason in result["reasons"]))

    def test_entry_classification_marks_early_recovery(self):
        from global_markets.market_analysis import classify_entry_opportunity
        daily = {"eligible": True, "latest_close": 98, "indicators": {
            "sma_20": 100, "rsi_14": 44, "macd_histogram": -0.1}}
        tactical = {"eligible": True, "latest_close": 101, "indicators": {
            "sma_20": 100, "rsi_14": 54, "macd_histogram": 0.2}}
        result = classify_entry_opportunity(daily, tactical, {"category": "possible_reversal"})
        self.assertEqual(result["category"], "recovery_watch")

    def test_entry_classification_requires_both_timeframes(self):
        from global_markets.market_analysis import classify_entry_opportunity
        result = classify_entry_opportunity(None, None)
        self.assertEqual(result["category"], "insufficient_data")
        self.assertIsNone(result["quality_score"])

    def test_daily_analysis_calculates_7d_and_30d_returns(self):
        result = analyze_candles(self.rows(count=60), now=self.now)
        self.assertIsNotNone(result["indicators"]["return_7d_pct"])
        self.assertIsNotNone(result["indicators"]["return_30d_pct"])
        self.assertGreater(result["indicators"]["return_30d_pct"], 0)

    def test_daily_analysis_exposes_31_point_normalized_history(self):
        result = analyze_candles(self.rows(count=60), now=self.now)
        history = result["normalized_history"]
        self.assertEqual(len(history), 31)
        self.assertEqual(history[0]["value"], 100.0)
        self.assertGreater(history[-1]["value"], 100.0)
        self.assertEqual(len({point["date"] for point in history}), 31)

    def test_intraday_analysis_does_not_expose_daily_comparison_history(self):
        result = analyze_candles(self.rows(count=60, interval="4h"), now=self.now)
        self.assertEqual(result["normalized_history"], [])

    def test_entry_filter_penalizes_extreme_volatility_and_recent_weakness(self):
        from global_markets.market_analysis import classify_entry_opportunity
        daily = {"eligible": True, "latest_close": 105, "indicators": {
            "sma_20": 100, "rsi_14": 58, "macd_histogram": 1},
            "risk_metrics": {"realized_volatility_20d_pct_annualized": 135,
                             "max_drawdown_120d_pct": -42, "return_20d_pct": -5}}
        tactical = {"eligible": True, "latest_close": 102, "indicators": {
            "sma_20": 100, "rsi_14": 55, "macd_histogram": 0.5}}
        result = classify_entry_opportunity(daily, tactical,
            {"category": "confirmed_trend"}, relative_strength_20d_pp=-4)
        self.assertEqual(result["risk_penalty"], 40)
        self.assertEqual(result["deterioration_penalty"], 16)
        self.assertEqual(result["quality_score"], 44)
        self.assertNotEqual(result["category"], "confirmed_entry_setup")

    def test_entry_filter_requires_daily_and_4h_confirmation(self):
        from global_markets.market_analysis import classify_entry_opportunity
        daily = {"eligible": True, "latest_close": 105, "indicators": {
            "sma_20": 100, "rsi_14": 58, "macd_histogram": 1}}
        tactical = {"eligible": True, "latest_close": 102, "indicators": {
            "sma_20": 100, "rsi_14": 48, "macd_histogram": -0.1}}
        result = classify_entry_opportunity(daily, tactical,
            {"category": "mixed_structure"})
        self.assertFalse(result["confirmed_both"])
        self.assertEqual(result["category"], "no_clear_opportunity")


if __name__ == "__main__":
    unittest.main()
