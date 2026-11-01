import unittest

from global_markets.alerts import build_technical_alerts


class TechnicalAlertTests(unittest.TestCase):
    def report(self):
        return {
            "analyses": [
                {"symbol": "BTCUSDT", "interval": "1d", "eligible": True,
                 "latest_candle_close": "2026-11-01T00:00:00+00:00",
                 "indicators": {"rsi_14": 51, "previous_rsi_14": 49,
                                "macd_12_26": 2, "macd_signal_9": 1,
                                "previous_macd_12_26": 0, "previous_macd_signal_9": 1}},
                {"symbol": "BTCUSDT", "interval": "4h", "eligible": True,
                 "latest_candle_close": "2026-11-01T12:00:00+00:00",
                 "indicators": {"rsi_14": 52, "previous_rsi_14": 51,
                                "macd_12_26": 3, "macd_signal_9": 2,
                                "previous_macd_12_26": 1, "previous_macd_signal_9": 2}},
            ],
            "cross_timeframe": [{
                "symbol": "BTCUSDT", "structure": "confirmed_trend",
                "relative_strength_vs_btc_7d_pct": 0,
                "relative_strength_vs_btc_30d_pct": 0,
            }],
        }

    def test_detects_confirmed_structure_rsi_and_macd_cross(self):
        alerts = build_technical_alerts(self.report())
        kinds = {item["event_type"] for item in alerts}
        self.assertIn("confirmed_trend", kinds)
        self.assertIn("rsi_cross_50_diari", kinds)
        self.assertIn("macd_bullish_cross_diari", kinds)
        self.assertIn("macd_bullish_cross_4h", kinds)

    def test_does_not_repeat_confirmed_structure_or_false_rsi_cross(self):
        report = self.report()
        report["analyses"][0]["indicators"]["previous_rsi_14"] = 50
        alerts = build_technical_alerts(report, {"BTCUSDT": "confirmed_trend"})
        kinds = {item["event_type"] for item in alerts}
        self.assertNotIn("confirmed_trend", kinds)
        self.assertNotIn("rsi_cross_50_diari", kinds)

    def test_relative_strength_requires_both_periods_positive(self):
        report = self.report()
        report["cross_timeframe"][0]["relative_strength_vs_btc_7d_pct"] = 1.2
        report["cross_timeframe"][0]["relative_strength_vs_btc_30d_pct"] = -0.1
        alerts = build_technical_alerts(report)
        self.assertNotIn("relative_strength_outperformance", {a["event_type"] for a in alerts})


if __name__ == "__main__":
    unittest.main()
