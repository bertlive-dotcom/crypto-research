"""Deterministic technical alert generation; alerts are informational only."""
from __future__ import annotations


def build_technical_alerts(report: dict, previous_structures: dict | None = None) -> list[dict]:
    previous_structures = previous_structures or {}
    analyses = {
        (row.get("symbol"), row.get("interval")): row
        for row in report.get("analyses", []) if row.get("eligible")
    }
    alerts = []
    for item in report.get("cross_timeframe", []):
        symbol = item.get("symbol")
        asset = symbol.replace("USDT", "") if isinstance(symbol, str) else str(symbol)
        daily = analyses.get((symbol, "1d"), {})
        tactical = analyses.get((symbol, "4h"), {})
        d = daily.get("indicators", {})
        h = tactical.get("indicators", {})
        d_close = daily.get("latest_candle_close", "")
        h_close = tactical.get("latest_candle_close", "")

        def add(kind, label, detail, stamp):
            alerts.append({
                "dedupe_key": f"{symbol}:{kind}:{stamp}",
                "event_type": kind, "asset": asset, "label": label,
                "detail": detail, "daily_close": d_close, "4h_close": h_close,
            })

        old = previous_structures.get(symbol)
        if item.get("structure") == "confirmed_trend" and old != "confirmed_trend":
            add("confirmed_trend", "Tendència multi-temporal confirmada",
                "La classificació ha entrat en tendència confirmada.", d_close + "|" + h_close)

        for frame, ind, stamp in (("diari", d, d_close), ("4h", h, h_close)):
            now_rsi, prior_rsi = ind.get("rsi_14"), ind.get("previous_rsi_14")
            if prior_rsi is not None and now_rsi is not None and prior_rsi < 50 <= now_rsi:
                add("rsi_cross_50_" + frame, "RSI ha creuat 50 (" + frame + ")",
                    f"RSI anterior {prior_rsi}; RSI actual {now_rsi}.", stamp)
            macd, signal = ind.get("macd_12_26"), ind.get("macd_signal_9")
            prev_macd, prev_signal = ind.get("previous_macd_12_26"), ind.get("previous_macd_signal_9")
            if None not in (macd, signal, prev_macd, prev_signal) and prev_macd <= prev_signal and macd > signal:
                add("macd_bullish_cross_" + frame, "Creuament alcista MACD (" + frame + ")",
                    "MACD ha passat de sota a sobre de la línia de senyal.", stamp)

        rel7 = item.get("relative_strength_vs_btc_7d_pct")
        rel30 = item.get("relative_strength_vs_btc_30d_pct")
        if rel7 is not None and rel30 is not None and rel7 > 0 and rel30 > 0:
            add("relative_strength_outperformance", "Supera BTC a 7 i 30 dies",
                f"Força relativa: {rel7:+.2f} pp a 7 dies i {rel30:+.2f} pp a 30 dies.",
                d_close)

    return alerts
