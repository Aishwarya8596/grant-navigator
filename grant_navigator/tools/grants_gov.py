"""Small, keyless client for the public Grants.gov discovery endpoints.

These tools return search and synopsis data. A full Notice of Funding
Opportunity is still needed before making a strong eligibility claim.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx


API_BASE_URL = "https://api.grants.gov/v1/api"
REQUEST_TIMEOUT_SECONDS = 15.0


class GrantsGovError(RuntimeError):
    """Raised when Grants.gov cannot provide a usable response."""


def _post_json(endpoint: str, payload: dict) -> dict:
    try:
        response = httpx.post(
            f"{API_BASE_URL}/{endpoint}",
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GrantsGovError(f"Grants.gov {endpoint} request failed") from exc

    if not isinstance(result, dict) or result.get("errorcode") != 0:
        message = result.get("msg", "invalid response") if isinstance(result, dict) else "invalid response"
        raise GrantsGovError(f"Grants.gov {endpoint}: {message}")

    data = result.get("data")
    if not isinstance(data, dict):
        raise GrantsGovError(f"Grants.gov {endpoint}: missing data")
    return data


def search_grants(keyword: str, rows: int = 10) -> dict:
    """Search posted federal grant opportunities by keyword.

    Args:
        keyword: A short description of the nonprofit's proposed project.
        rows: Number of search results to return, from 1 to 25.

    Returns:
        Search results with IDs, titles, agencies, status, and dates.
    """
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword must not be blank")
    if not 1 <= rows <= 25:
        raise ValueError("rows must be between 1 and 25")

    data = _post_json(
        "search2", {"keyword": keyword, "oppStatuses": "posted", "rows": rows}
    )
    hits = data.get("oppHits")
    if not isinstance(hits, list):
        raise GrantsGovError("Grants.gov search2: missing opportunity hits")

    retrieved_at = datetime.now(timezone.utc).isoformat()
    return {
        "status": "success",
        "keyword": keyword,
        "total_results": data.get("hitCount", len(hits)),
        "retrieved_at_utc": retrieved_at,
        "source_api": f"{API_BASE_URL}/search2",
        "opportunities": [
            {
                "id": hit.get("id"),
                "number": hit.get("number"),
                "title": hit.get("title"),
                "agency": hit.get("agencyName"),
                "status": hit.get("oppStatus"),
                "open_date": hit.get("openDate"),
                "close_date": hit.get("closeDate"),
                "retrieved_at_utc": retrieved_at,
            }
            for hit in hits
            if isinstance(hit, dict)
        ],
    }


def fetch_grant_details(opportunity_id: int) -> dict:
    """Fetch a Grants.gov opportunity synopsis and document metadata.

    Args:
        opportunity_id: Numeric ID returned by search_grants.

    Returns:
        Synopsis, applicant categories, funding fields, and document metadata.
    """
    if opportunity_id <= 0:
        raise ValueError("opportunity_id must be positive")

    data = _post_json("fetchOpportunity", {"opportunityId": opportunity_id})
    synopsis = data.get("synopsis") or {}
    if not isinstance(synopsis, dict):
        synopsis = {}
    # The free-text synopsis.agencyName can contain a grantor contact.
    # Both levels of agencyDetails refer to the publishing agency record.
    agency = None
    for metadata in (data.get("agencyDetails"), synopsis.get("agencyDetails")):
        name = metadata.get("agencyName") if isinstance(metadata, dict) else None
        if isinstance(name, str) and name.strip():
            agency = name.strip()
            break

    return {
        "status": "success",
        "id": data.get("id"),
        "number": data.get("opportunityNumber"),
        "title": data.get("opportunityTitle"),
        "agency": agency,
        "description": synopsis.get("synopsisDesc"),
        "applicant_types": [
            item.get("description")
            for item in synopsis.get("applicantTypes", [])
            if isinstance(item, dict)
        ],
        "cost_sharing": synopsis.get("costSharing"),
        "award_floor": synopsis.get("awardFloor"),
        "award_ceiling": synopsis.get("awardCeiling"),
        "response_date": data.get("responseDate") or synopsis.get("responseDate"),
        "document_urls": data.get("synopsisDocumentURLs", []),
        "attachment_folders": data.get("synopsisAttachmentFolders", []),
        "source_api": f"{API_BASE_URL}/fetchOpportunity",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
