"""Manual, read-only FinancialData.Net seed-symbol coverage audit."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from global_markets.config import DEFAULT_UNIVERSE_SEEDS
from global_markets.providers.financialdata import FinancialDataClient, FinancialDataError


# FinancialData.Net documents these symbol directories as requiring paid tiers.
# Keep the free-tier audit focused on endpoints the account is expected to access.
MINIMUM_PLAN = {
    "index": "standard",
    "crypto": "standard",
    "future": "standard",
    "forex": "premium",
}


def main() -> int:
    api_key = os.environ.get("FINANCIALDATA_API_KEY", "").strip()
    if not api_key:
        print("FINANCIALDATA_API_KEY secret is missing.")
        return 2

    client = FinancialDataClient(api_key, timeout=15, max_retries=2, max_pages=10)
    report = {
        "provider": "FinancialData.Net",
        "assumed_plan": "free",
        "mode": "read-only symbol-directory audit; no orders or price downloads",
        "asset_classes": {},
    }

    for asset_class, seeds in DEFAULT_UNIVERSE_SEEDS.items():
        required_plan = MINIMUM_PLAN.get(asset_class)
        if required_plan:
            report["asset_classes"][asset_class] = {
                "status": f"requires_{required_plan}_plan",
                "requested": seeds,
                "reason": (
                    f"FinancialData.Net documents this symbol directory as "
                    f"requiring the {required_plan.capitalize()} subscription."
                ),
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
            # FinancialDataError messages are locally defined, sanitized status descriptions;
            # do not include response bodies, request URLs, query parameters or credentials.
            report["asset_classes"][asset_class] = {
                "status": "request_error",
                "requested": seeds,
                "diagnostic": str(exc),
            }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
