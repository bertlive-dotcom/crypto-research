"""Read-only equity research universe and daily technical screening."""
from datetime import datetime, timezone

from global_markets.market_analysis import analyze_candles
from global_markets.providers.financialdata import FinancialDataClient, FinancialDataError

EQUITY_UNIVERSE = [
    {"symbol": "NVDA", "name": "Nvidia", "international": False},
    {"symbol": "TSM", "name": "TSMC", "international": False},
    {"symbol": "ASML", "name": "ASML", "international": False},
    {"symbol": "MSFT", "name": "Microsoft", "international": False},
    {"symbol": "GOOGL", "name": "Alphabet", "international": False},
    {"symbol": "AMZN", "name": "Amazon", "international": False},
    {"symbol": "AVGO", "name": "Broadcom", "international": False},
    {"symbol": "SU.PA", "name": "Schneider Electric", "international": True},
]


def analyse_equity_universe(client, limit=120, now=None):
    """Fetch each symbol independently and retain per-symbol errors."""
    analyses, unavailable, quality = [], [], []
    for item in EQUITY_UNIVERSE:
        symbol = item["symbol"]
        try:
            feed = client.fetch_daily_prices_with_quality(
                symbol, "equity", international=item["international"], limit=limit
            )
            result = analyze_candles(feed["candles"], now=now, max_age_seconds=5 * 86400)
            result.update({
                "symbol": symbol,
                "name": item["name"],
                "asset_class": "equity",
                "source_records": feed["source_records"],
                "valid_records": len(feed["candles"]),
                "rejected_records": len(feed["rejected_records"]),
            })
            analyses.append(result)
            if feed["rejected_records"]:
                quality.append({
                    "symbol": symbol,
                    "rejected_records": len(feed["rejected_records"]),
                    "examples": "; ".join(
                        "{}: {}".format(row["date"], row["reason"])
                        for row in feed["rejected_records"][:3]
                    ),
                })
        except (FinancialDataError, ValueError) as error:
            unavailable.append({
                "symbol": symbol, "name": item["name"], "reason": str(error)
            })
    analyses.sort(
        key=lambda row: (
            bool(row.get("eligible")),
            row.get("technical_screen_score")
            if row.get("technical_screen_score") is not None else -1,
        ),
        reverse=True,
    )
    return {
        "source": "FinancialData.Net",
        "observed_at": (now or datetime.now(timezone.utc)).isoformat(),
        "analyses": analyses,
        "unavailable": unavailable,
        "quality": quality,
        "universe_size": len(EQUITY_UNIVERSE),
        "valid_count": sum(bool(row.get("eligible")) for row in analyses),
    }
