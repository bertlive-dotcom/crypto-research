"""Manual, read-only FinancialData.Net seed-symbol coverage audit."""
from __future__ import annotations

import json
import os
import sys

from global_markets.config import DEFAULT_UNIVERSE_SEEDS
from global_markets.providers.financialdata import FinancialDataClient, FinancialDataError


def main() -> int:
    api_key = os.environ.get("FINANCIALDATA_API_KEY", "").strip()
    if not api_key:
        print("FINANCIALDATA_API_KEY secret is missing.")
        return 2

    client = FinancialDataClient(api_key, timeout=15, max_retries=2, max_pages=10)
    report = {
        "provider": "FinancialData.Net",
        "mode": "read-only symbol-directory audit; no orders or price downloads",
        "asset_classes": {},
    }

    for asset_class, seeds in DEFAULT_UNIVERSE_SEEDS.items():
        if asset_class == "index":
            report["asset_classes"][asset_class] = {
                "status": "not_checked",
                "reason": "No index symbol-directory endpoint is configured in this adapter.",
                "requested": seeds,
            }
            continue
        try:
            matches = client.find_symbols(asset_class, seeds)
            found = [symbol for symbol, record in matches.items() if record is not None]
            missing = [symbol for symbol, record in matches.items() if record is None]
            report["asset_classes"][asset_class] = {
                "status": "checked",
                "requested_count": len(seeds),
                "matched_count": len(found),
                "missing_count": len(missing),
                "matched": found,
                "missing": missing,
            }
        except (FinancialDataError, ValueError) as exc:
            # Deliberately omit exception details; provider errors may contain request metadata.
            report["asset_classes"][asset_class] = {
                "status": "unavailable_or_plan_restricted",
                "requested": seeds,
                "note": type(exc).__name__,
            }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
