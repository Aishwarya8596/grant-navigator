"""Preserve unknown API facts and distinguish general dates from eligibility."""

from datetime import date, datetime, timezone

import pytest

from grant_navigator.opportunities import (
    OpportunityRecord,
    check_general_deadline,
    normalize_opportunity,
    parse_general_deadline_date,
)


def detail(**updates):
    return {
        "status": "success", "id": 363696, "number": "AC-08-28-26",
        "title": "AmeriCorps example", "description": "Community service",
        "applicant_types": ["Nonprofits having 501(c)(3) status"],
        "cost_sharing": True, "award_floor": "none", "award_ceiling": "none",
        "response_date": "Jan 13, 2027 12:00:00 AM EST",
        "source_api": "https://api.grants.gov/v1/api/fetchOpportunity",
        **updates,
    }


def test_saved_fixture_is_not_made_current_and_transport_success_is_not_domain_status():
    record = normalize_opportunity(detail())

    assert record.opportunity_id == 363696
    assert record.opportunity_status is None and record.status_source == "unavailable"
    assert record.retrieved_at_utc is None
    assert record.award_floor_raw == record.award_ceiling_raw == "none"
    assert record.award_floor_usd is record.award_ceiling_usd is None
    assert record.api_general_deadline_date == date(2027, 1, 13)
    assert record.api_general_deadline_raw == "Jan 13, 2027 12:00:00 AM EST"
    assert record.source_page.endswith("/363696")


@pytest.mark.parametrize("status", ["error", "failed"])
def test_failed_detail_response_cannot_become_opportunity_facts(status):
    with pytest.raises(ValueError, match="successful detail response"):
        normalize_opportunity(detail(status=status))


def test_matching_search_hit_supplies_status_and_agency_without_inferred_geography():
    hit = {
        "id": "363696", "number": "AC-08-28-26", "status": "posted",
        "agency": "AmeriCorps", "open_date": "08/28/2026", "close_date": "01/13/2027",
        "retrieved_at_utc": "2026-11-13T08:00:00+00:00",
    }
    record = normalize_opportunity(detail(), hit, retrieved_at="2026-11-13T00:30:00-08:00")

    assert record.opportunity_status == "posted" and record.status_source == "search"
    assert record.agency == "AmeriCorps"
    assert record.search_open_date == date(2026, 8, 28)
    assert record.search_close_date == date(2027, 1, 13)
    assert record.retrieved_at_utc == datetime(2026, 11, 13, 8, 30, tzinfo=timezone.utc)
    assert record.search_retrieved_at_utc == datetime(2026, 11, 13, 8, tzinfo=timezone.utc)
    assert "service_area" not in record.model_dump()


@pytest.mark.parametrize("hit", [
    {"id": "123", "number": "AC-08-28-26"},
    {"id": "363696", "number": "ANOTHER-GRANT"},
])
def test_mismatched_search_identity_is_rejected(hit):
    with pytest.raises(ValueError, match="do not match"):
        normalize_opportunity(detail(), hit)


@pytest.mark.parametrize("identifier", [None, True, 0, -1, 1.5, "not-an-id"])
def test_missing_or_invalid_detail_identity_is_rejected(identifier):
    with pytest.raises(ValueError, match="positive integer"):
        normalize_opportunity(detail(id=identifier))


@pytest.mark.parametrize("raw", [
    "01/13/2027", "1/13/2027", "2027-01-13", "2027-01-13T00:00:00Z",
    "2027-01-13T23:00:00-08:00", "Jan 13, 2027 12:00:00 AM EST",
    "Jan13,2027 12AM EST", "January 13, 2027", date(2027, 1, 13),
])
def test_known_date_formats_preserve_source_calendar_date(raw):
    assert parse_general_deadline_date(raw) == date(2027, 1, 13)


@pytest.mark.parametrize("raw", [
    None, "", "none", "See full notice", "13/99/2027", "2027-02-30",
    "2027-01-13 garbage", "Jan 13, 2027 99:00 AM EST", "Janupry 13, 2027", 0,
])
def test_unknown_or_unparseable_dates_remain_unknown(raw):
    assert parse_general_deadline_date(raw) is None


def test_search_date_can_fill_unparseable_detail_without_losing_either_raw_source():
    record = normalize_opportunity(detail(response_date="See full notice"), {
        "id": "363696", "number": "AC-08-28-26", "close_date": "01/13/2027",
    })
    assert record.api_general_deadline_date == date(2027, 1, 13)
    assert record.api_general_deadline_source == "search_close_date"
    assert record.detail_response_date_raw == "See full notice"
    assert record.api_general_deadline_raw == record.search_close_date_raw == "01/13/2027"
    assert any("unparseable" in item for item in record.warnings)


def test_conflicting_general_deadlines_are_flagged_without_silently_discarding_search_date():
    record = normalize_opportunity(detail(), {"id": "363696", "close_date": "01/12/2027"})
    assert record.api_general_deadline_date == date(2027, 1, 13)
    assert record.search_close_date == date(2027, 1, 12)
    assert any("different general deadline dates" in item for item in record.warnings)


@pytest.mark.parametrize("raw, expected", [("$1,000.50", 1000.50), ("0", 0), (0, 0), ("25000", 25000)])
def test_numeric_funding_and_explicit_zero_are_preserved(raw, expected):
    record = normalize_opportunity(detail(award_floor=raw, award_ceiling=None))
    assert record.award_floor_usd == expected
    assert record.award_floor_raw == str(raw)
    assert record.award_ceiling_usd is None


@pytest.mark.parametrize("raw", [True, -1, float("nan"), float("inf"), "1,2", "many", 10**1000])
def test_unusable_funding_does_not_become_zero_or_an_exclusion_amount(raw):
    record = normalize_opportunity(detail(award_floor=raw))
    assert record.award_floor_usd is None
    assert record.award_floor_raw == str(raw)
    assert any("award_floor" in item for item in record.warnings)


def test_inconsistent_range_remains_unresolved():
    record = normalize_opportunity(detail(award_floor="20000", award_ceiling="10000"))
    assert record.award_floor_usd is record.award_ceiling_usd is None
    assert record.award_floor_raw == "20000" and record.award_ceiling_raw == "10000"
    assert any("inconsistent" in item for item in record.warnings)


def test_false_cost_sharing_is_not_missing_and_invalid_truthy_text_is_not_a_rule():
    assert normalize_opportunity(detail(cost_sharing=False)).cost_sharing is False
    invalid = normalize_opportunity(detail(cost_sharing="yes"))
    assert invalid.cost_sharing is None
    assert any("not a boolean" in item for item in invalid.warnings)


@pytest.mark.parametrize("as_of, expected", [
    ("2027-01-12", "future"), ("2027-01-13", "on_as_of_date"), ("2027-01-14", "past"),
])
def test_general_deadline_comparison_never_confirms_applicant_specific_deadline(as_of, expected):
    result = check_general_deadline(normalize_opportunity(detail()), as_of)
    assert result.status == expected
    assert result.scope == "api_general"
    assert result.applicant_specific_verified is False
    assert "earlier deadlines" in result.note
    assert "exact times" in result.note


def test_missing_deadline_check_remains_unknown():
    result = check_general_deadline(normalize_opportunity(detail(response_date="")), date(2026, 11, 13))
    assert result.status == "unknown" and result.deadline_date is None


@pytest.mark.parametrize("as_of", ["tomorrow", 123, datetime(2026, 11, 13)])
def test_deadline_check_requires_explicit_calendar_date(as_of):
    with pytest.raises(ValueError, match="calendar date"):
        check_general_deadline(normalize_opportunity(detail()), as_of)


def test_retrieval_time_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone"):
        normalize_opportunity(detail(), retrieved_at="2026-11-13T08:00:00")
    with pytest.raises(ValueError, match="timezone"):
        OpportunityRecord(opportunity_id=363696, source_page="https://www.grants.gov/search-results-detail/363696", retrieved_at_utc=datetime(2026, 11, 13))


def test_success_from_search_transport_is_not_a_domain_status():
    record = normalize_opportunity(detail(), {"id": "363696", "status": "success"})
    assert record.opportunity_status is None and record.status_source == "unavailable"


def test_explicit_domain_status_takes_precedence_and_conflict_is_visible():
    record = normalize_opportunity(detail(opportunity_status="closed"), {"id": "363696", "status": "posted"})
    assert record.opportunity_status == "closed" and record.status_source == "detail"
    assert any("different opportunity statuses" in item for item in record.warnings)
