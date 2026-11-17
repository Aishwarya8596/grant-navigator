"""Tests for the public Grants.gov response contract we depend on."""

from datetime import datetime

import pytest

from grant_navigator.tools import grants_gov


def test_search_preserves_missing_deadline_for_later_verification(monkeypatch):
    def fake_post(endpoint, payload):
        assert endpoint == "search2"
        assert payload == {"keyword": "community", "oppStatuses": "posted", "rows": 5}
        return {
            "hitCount": 1,
            "oppHits": [
                {
                    "id": "363696",
                    "number": "AC-08-28-26",
                    "title": "FY 2027 AmeriCorps State and National Competitive Grants",
                    "agencyName": "AmeriCorps",
                    "oppStatus": "posted",
                    "openDate": "08/28/2026",
                    "closeDate": "",
                }
            ],
        }

    monkeypatch.setattr(grants_gov, "_post_json", fake_post)
    result = grants_gov.search_grants(" community ", rows=5)

    assert result["total_results"] == 1
    assert result["opportunities"][0]["id"] == "363696"
    assert result["opportunities"][0]["close_date"] == ""
    assert result["source_api"].endswith("/search2")
    assert datetime.fromisoformat(result["retrieved_at_utc"]).tzinfo is not None
    assert result["opportunities"][0]["retrieved_at_utc"] == result["retrieved_at_utc"]


def test_fetch_does_not_invent_a_numeric_award_range(monkeypatch):
    def fake_post(endpoint, payload):
        assert endpoint == "fetchOpportunity"
        assert payload == {"opportunityId": 363696}
        return {
            "id": 363696,
            "opportunityNumber": "AC-08-28-26",
            "opportunityTitle": "FY 2027 AmeriCorps State and National Competitive Grants",
            "agencyDetails": {"agencyName": "AmeriCorps"},
            "synopsis": {
                "agencyName": "Example contact\nGrantor",
                "synopsisDesc": "Community service grants",
                "applicantTypes": [{"id": "12", "description": "Nonprofits with 501(c)(3) status"}],
                "awardFloor": "none",
                "awardCeiling": "none",
                "costSharing": True,
            },
            "synopsisDocumentURLs": [
                {"url": "https://www.americorps.gov/funding-opportunity/example"}
            ],
        }

    monkeypatch.setattr(grants_gov, "_post_json", fake_post)
    result = grants_gov.fetch_grant_details(363696)

    assert result["award_floor"] == "none"
    assert result["award_ceiling"] == "none"
    assert result["applicant_types"] == ["Nonprofits with 501(c)(3) status"]
    assert result["document_urls"]
    assert result["agency"] == "AmeriCorps"
    assert datetime.fromisoformat(result["retrieved_at_utc"]).tzinfo is not None
    assert "opportunity_status" not in result  # The documented detail schema does not provide it.


@pytest.mark.parametrize(("synopsis_metadata", "expected"), [
    ({"agencyDetails": {"agencyName": "Documented agency name"}}, "Documented agency name"),
    ({}, None),
])
def test_fetch_uses_structured_agency_or_leaves_name_unknown(monkeypatch, synopsis_metadata, expected):
    monkeypatch.setattr(grants_gov, "_post_json", lambda endpoint, payload: {
        "id": 363696, "opportunityTitle": "A title mentioning AmeriCorps",
        "synopsis": {"agencyName": "Grant officer", **synopsis_metadata},
    })
    assert grants_gov.fetch_grant_details(363696)["agency"] == expected


def test_rejects_blank_search_before_network_call():
    with pytest.raises(ValueError, match="blank"):
        grants_gov.search_grants("  ")
