"""Save one dated Grants.gov detail record for development and evaluation.

This script uses only public Grants.gov endpoints. It does not download the
full notice; that document is curated separately because API attachment
metadata does not always contain a usable download URL.
"""

from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path

from grant_navigator.tools.grants_gov import fetch_grant_details, search_grants


EXAMPLE_ID = 363696
OUTPUT_PATH = Path("data/fixtures/americorps_363696.json")
NOTICE_PATH = Path("data/notices/FY27_ASNCompetitiveNotice_Final.508.pdf")


def main() -> None:
    search = search_grants("community", rows=5)
    detail = fetch_grant_details(EXAMPLE_ID)
    notice_checksum = sha256(NOTICE_PATH.read_bytes()).hexdigest() if NOTICE_PATH.exists() else None
    snapshot = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "query_check": {
            "keyword": search["keyword"],
            "total_results": search["total_results"],
        },
        "opportunity": detail,
        "full_notice": {
            "source_page": "https://www.americorps.gov/funding-opportunity/fy-2027-americorps-state-national-grants",
            "official_state_mirror": "https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf",
            "local_path": str(NOTICE_PATH),
            "sha256": notice_checksum,
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    print(
        f"Saved {detail['number']} ({detail['title']}) to {OUTPUT_PATH}; "
        f"search returned {search['total_results']} candidates."
    )


if __name__ == "__main__":
    main()
