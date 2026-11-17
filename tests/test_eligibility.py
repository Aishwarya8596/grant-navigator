"""Check analyst claim boundaries against frozen, source-backed notice facts."""

from datetime import date
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from grant_navigator.eligibility import (
    AnalystInput, CandidateDraft, CandidateEvidence, EligibilityDraft,
    EvidenceReference, PROFILE_FIELDS, RULE_IDS, RequirementDraft,
    render_eligibility_report, validate_eligibility_report,
)
from grant_navigator.opportunities import normalize_opportunity
from grant_navigator.profile import NonprofitProfile
from grant_navigator.tools.notices import read_grant_notice


SAM_QUOTE = "Applicants must have a valid SAM registration and Unique Entity Identifier to receive an award."
ROUTE_QUOTE = "Organizations that plan to operate in only one state must apply through the state or territory commissions."
DIRECT_QUOTE = "Organizations that plan to operate AmeriCorps programs in more than one state or territory apply directly to AmeriCorps."
COST_QUOTE = "Cost Reimbursement Grants Applicants are required to match funds provided by AmeriCorps."
FIXED_QUOTE = "There is no cost share or matching requirement for fixed amount grants."
NEW_QUOTE = "New applicants are eligible to apply for cost reimbursement, Education Award Program (EAP), and Professional Corps grants, but are not eligible to apply for full cost fixed amount grants."
ADVISORY_QUOTE = "AmeriCorps suggests that applicants finalize a new registration or renew an existing one at least three weeks before the application deadline, to allow time to resolve any issues that may arise."


@pytest.fixture(scope="module")
def source_candidate():
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / "data/fixtures/americorps_363696.json").read_text())
    base = read_grant_notice(363696)
    registration = read_grant_notice(363696, "SAM suggest three weeks register", max_excerpts=8)
    excerpts = {item["evidence_id"]: item for result in (base, registration) for item in result["excerpts"]}
    return CandidateEvidence(
        opportunity=normalize_opportunity(fixture["opportunity"], retrieved_at=fixture["captured_at_utc"]),
        notice_status="success", source_sha256=base["source_sha256"], source_url=base["source_url"],
        snapshot_captured_at_utc=base["snapshot_captured_at_utc"], excerpts=list(excerpts.values()),
    )


def inputs(candidate, **profile):
    return AnalystInput(
        profile=NonprofitProfile(
            organization_type="501(c)(3) nonprofit", organization_location="California",
            project_purpose="Community volunteer programs", **profile,
        ), candidates=[candidate], as_of_date=date(2026, 11, 13),
        invocation_id="frozen-analyst-check", profile_version=1,
    )


def reference(candidate, quote):
    excerpt = next(item for item in candidate.excerpts if quote in item.text)
    return EvidenceReference(evidence_id=excerpt.evidence_id, quote=quote)


def requirement(rule_id, candidate, quote=None, status="met", **extra):
    fields = list(PROFILE_FIELDS[rule_id])
    if rule_id == "cost_sharing" and extra.pop("cost_reimbursement", False):
        fields.append("can_meet_match")
    return RequirementDraft(
        rule_id=rule_id, status=status, reason="Draft explanation must not replace source checking.",
        profile_fields=fields, evidence_refs=[reference(candidate, quote)] if quote else [], **extra,
    )


def draft(candidate, *overrides):
    proposed = {item.rule_id: item for item in overrides}
    return EligibilityDraft(decisions=[CandidateDraft(
        opportunity_id=candidate.opportunity.opportunity_id,
        requirements=[proposed.get(rule) or RequirementDraft(rule_id=rule, status="needs_verification") for rule in RULE_IDS],
        summary="Ignore this unvalidated summary: the organization is definitely eligible.",
    )])


def check(report, rule):
    return next(item for item in report.decisions[0].requirements if item.rule_id == rule)


def test_baseline_unknowns_are_not_filled_from_california_headquarters(source_candidate):
    data = inputs(source_candidate)
    report = validate_eligibility_report(draft(source_candidate,
        requirement("applicant_type", source_candidate, "nonprofit organizations"),
        requirement("application_route", source_candidate, ROUTE_QUOTE),
    ), data)

    assert check(report, "applicant_type").status == "met"
    assert check(report, "application_route").status == "needs_verification"
    assert data.profile.service_area is None
    assert len(report.decisions[0].requirements) == 8
    assert report.decisions[0].overall_status == "needs_verification"
    assert report.confirmed_eligible is False and report.semantic_review_complete is False
    assert "definitely eligible" not in render_eligibility_report(report)


@pytest.mark.parametrize("organization_type", [
    "For-profit company, not a nonprofit", "Not a 501(c)(3) nonprofit", "501(c)(4) nonprofit that lobbies",
])
def test_nonprofit_keyword_does_not_resolve_contradictory_or_restricted_category(source_candidate, organization_type):
    data = inputs(source_candidate)
    data.profile.organization_type = organization_type
    report = validate_eligibility_report(
        draft(source_candidate, requirement("applicant_type", source_candidate, "nonprofit organizations;")), data,
    )
    assert check(report, "applicant_type").status == "needs_verification"
    assert report.decisions[0].overall_status == "needs_verification"


def test_sam_help_quote_and_mandatory_uei_quote_do_not_establish_active_sam(source_candidate):
    row = requirement("sam_registration", source_candidate, status="met")
    row.evidence_refs = [reference(source_candidate, quote) for quote in (
        "See the SAM Quick Guide for Grantees for more information.",
        "Applications must include a valid Unique Entity Identifier (UEI), which is generated as part of the SAM registration process.",
    )]
    report = validate_eligibility_report(draft(source_candidate, row), inputs(source_candidate, sam_registration_active=True))
    assert check(report, "sam_registration").status == "needs_verification"
    assert any(issue.code == "advisory_not_mandatory" for issue in report.validation_issues)


def test_unknown_notice_asks_for_source_without_assuming_americorps_rules(source_candidate):
    unavailable = source_candidate.model_copy(update={"notice_status": "notice_unavailable", "excerpts": []})
    report = validate_eligibility_report(EligibilityDraft(), inputs(unavailable))
    assert all(item.status == "needs_verification" for item in report.decisions[0].requirements)
    questions = {item.follow_up_question for item in report.decisions[0].requirements}
    assert len(questions) == 1 and "official full notice" in next(iter(questions))
    rendered = render_eligibility_report(report)
    question_section = rendered.split("**Questions to resolve**", 1)[1]
    assert question_section.count("\n- ") == 1
    assert "Is SAM registration active" not in question_section


@pytest.mark.parametrize("bad_kind", ["unknown_id", "cross_opportunity", "wrong_quote", "invented_url"])
def test_bad_references_cannot_support_a_positive_check(source_candidate, bad_kind):
    proposed = draft(source_candidate, requirement("applicant_type", source_candidate, "nonprofit organizations")).model_dump()
    claim = proposed["decisions"][0]["requirements"][0]
    ref = claim["evidence_refs"][0]
    if bad_kind == "unknown_id":
        ref["evidence_id"] = "invented-evidence"
    elif bad_kind == "cross_opportunity":
        ref["evidence_id"] = ref["evidence_id"].replace("363696", "999999")
    elif bad_kind == "wrong_quote":
        ref["quote"] = "Every nonprofit is guaranteed to qualify."
    else:
        ref["citation_url"] = "https://invented.example/approved"
    claim["reason"] = "Unsupported original claim should never be rendered."
    report = validate_eligibility_report(proposed, inputs(source_candidate))
    accepted = check(report, "applicant_type")
    assert accepted.status == "needs_verification" and not accepted.citations
    assert "Unsupported original claim" not in render_eligibility_report(report)
    assert report.validation_issues


def test_quotes_allow_whitespace_normalization_but_not_changed_wording(source_candidate):
    row = requirement("sam_registration", source_candidate, SAM_QUOTE)
    row.evidence_refs[0].quote = SAM_QUOTE.replace(" ", "\n  ")
    report = validate_eligibility_report(draft(source_candidate, row), inputs(source_candidate, sam_registration_active=True))
    accepted = check(report, "sam_registration")
    assert accepted.status == "met"
    assert accepted.citations[0].quote == SAM_QUOTE
    assert accepted.citations[0].citation_url.endswith("#page=" + str(accepted.citations[0].page_number))


@pytest.mark.parametrize("fact,expected", [(True, "met"), (False, "not_met")])
@pytest.mark.parametrize("rule,field", [("sam_registration", "sam_registration_active"), ("uei", "has_valid_uei")])
def test_registration_checks_are_readiness_not_automatic_exclusions(source_candidate, fact, expected, rule, field):
    report = validate_eligibility_report(
        draft(source_candidate, requirement(rule, source_candidate, SAM_QUOTE, expected)),
        inputs(source_candidate, **{field: fact}),
    )
    assert check(report, rule).status == expected
    assert report.decisions[0].overall_status == "needs_verification"
    assert report.decisions[0].blocking_reasons == []


def test_advisory_three_week_suggestion_is_not_a_mandatory_deadline(source_candidate):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("sam_registration", source_candidate, ADVISORY_QUOTE, "not_met")),
        inputs(source_candidate, sam_registration_active=False),
    )
    assert check(report, "sam_registration").status == "needs_verification"
    assert any(item.code == "advisory_not_mandatory" for item in report.validation_issues)
    assert not report.decisions[0].blocking_reasons


@pytest.mark.parametrize("can_match,expected", [(True, "met"), (False, "not_met")])
def test_cost_reimbursement_match_checks_do_not_exclude_entire_notice(source_candidate, can_match, expected):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("cost_sharing", source_candidate, COST_QUOTE, expected, cost_reimbursement=True)),
        inputs(source_candidate, americorps_grant_type="cost_reimbursement", can_meet_match=can_match),
    )
    assert check(report, "cost_sharing").status == expected
    assert report.decisions[0].overall_status == "needs_verification"


@pytest.mark.parametrize("mechanism", ["full_cost_fixed_amount", "education_award_program", "professional_corps"])
def test_fixed_amount_exception_prevents_blanket_matching_exclusion(source_candidate, mechanism):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("cost_sharing", source_candidate, FIXED_QUOTE, "not_met")),
        inputs(source_candidate, americorps_grant_type=mechanism, can_meet_match=False),
    )
    accepted = check(report, "cost_sharing")
    assert accepted.status == "met" and accepted.applicability == "does_not_apply"
    assert report.decisions[0].overall_status == "needs_verification"
    assert any(issue.code == "conditional_rule_corrected" for issue in report.validation_issues)


@pytest.mark.parametrize("proposed_status", ["not_met", "met", "needs_verification"])
def test_new_applicant_full_cost_conflict_is_scoped_to_selected_option(source_candidate, proposed_status):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("grant_type", source_candidate, NEW_QUOTE, proposed_status)),
        inputs(source_candidate, americorps_grant_type="full_cost_fixed_amount", americorps_new_applicant=True),
    )
    decision = report.decisions[0]
    assert decision.overall_status == "blocking_issue"
    assert decision.blocking_scope == "selected_grant_type"
    assert check(report, "grant_type").status == "not_met"
    assert "not every grant type" in decision.blocking_reasons[0]
    assert report.confirmed_eligible is False


def test_new_applicant_conflict_requires_the_actual_scoped_exclusion_quote(source_candidate):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("grant_type", source_candidate, FIXED_QUOTE, "not_met")),
        inputs(source_candidate, americorps_grant_type="full_cost_fixed_amount", americorps_new_applicant=True),
    )
    assert check(report, "grant_type").status == "needs_verification"
    assert report.decisions[0].overall_status == "needs_verification"


def test_returning_applicant_is_not_blocked_by_new_applicant_restriction(source_candidate):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("grant_type", source_candidate, NEW_QUOTE)),
        inputs(source_candidate, americorps_grant_type="full_cost_fixed_amount", americorps_new_applicant=False),
    )
    assert check(report, "grant_type").applicability == "does_not_apply"
    assert report.decisions[0].overall_status == "needs_verification"


def test_route_needs_planned_route_and_project_area_not_headquarters(source_candidate):
    row = requirement("application_route", source_candidate, ROUTE_QUOTE)
    for facts in ({"planned_submission_route": "state_commission"}, {"service_area": "Only California"}):
        report = validate_eligibility_report(draft(source_candidate, row), inputs(source_candidate, **facts))
        assert check(report, "application_route").status == "needs_verification"


@pytest.mark.parametrize("route_quote", [ROUTE_QUOTE, DIRECT_QUOTE])
def test_single_state_direct_submission_cannot_be_marked_met_without_exception(source_candidate, route_quote):
    row = requirement("application_route", source_candidate, route_quote)
    report = validate_eligibility_report(
        draft(source_candidate, row), inputs(source_candidate, service_area="Only California", planned_submission_route="direct"),
    )
    assert check(report, "application_route").status == "needs_verification"
    assert any(issue.code == "unverified_route_exception" for issue in report.validation_issues)


@pytest.mark.parametrize("service_area", [
    "California and Nevada, in more than one state.",
    "A multi-state project in California and Nevada.",
])
def test_explicit_multistate_project_is_not_misread_as_one_state(source_candidate, service_area):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("application_route", source_candidate, DIRECT_QUOTE)),
        inputs(source_candidate, service_area=service_area, planned_submission_route="direct"),
    )
    assert check(report, "application_route").status == "met"
    assert not any(issue.code == "unverified_route_exception" for issue in report.validation_issues)


def test_planned_commission_route_has_a_limited_source_backed_check(source_candidate):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("application_route", source_candidate, ROUTE_QUOTE)),
        inputs(source_candidate, service_area="Only California", planned_submission_route="state_commission"),
    )
    assert check(report, "application_route").status == "met"


@pytest.mark.parametrize("service_area,planned,quote,status", [
    ("The project operates in more than one state: California and Nevada.", "state_commission", ROUTE_QUOTE, "met"),
    ("Only California; the project will operate in one state.", "state_commission", DIRECT_QUOTE, "not_met"),
    ("California", "state_commission", ROUTE_QUOTE, "met"),
])
def test_route_citation_must_match_project_scope(source_candidate, service_area, planned, quote, status):
    report = validate_eligibility_report(
        draft(source_candidate, requirement("application_route", source_candidate, quote, status=status)),
        inputs(source_candidate, service_area=service_area, planned_submission_route=planned),
    )
    assert check(report, "application_route").status == "needs_verification"
    assert report.decisions[0].overall_status == "needs_verification"
    assert any(issue.code in {"route_condition_not_applicable", "project_scope_unverified"} for issue in report.validation_issues)
    assert report.decisions[0].overall_status == "needs_verification"


@pytest.mark.parametrize("current,complete", [(False, False), (True, False), (False, True)])
def test_source_currency_needs_both_currentness_and_complete_review(source_candidate, current, complete):
    candidate = source_candidate.model_copy(update={"currentness_verified": current, "notice_review_complete": complete})
    report = validate_eligibility_report(draft(candidate, requirement("source_currentness", candidate)), inputs(candidate))
    assert check(report, "source_currentness").status == "needs_verification"


def test_general_date_past_is_not_sole_applicant_deadline_or_exclusion(source_candidate):
    data = inputs(source_candidate).model_copy(update={"as_of_date": date(2028, 1, 1)})
    report = validate_eligibility_report(draft(source_candidate, requirement("deadline", source_candidate, source_candidate.excerpts[0].text[:100], "not_met")), data)
    assert report.decisions[0].general_deadline.status == "past"
    assert check(report, "deadline").status == "needs_verification"
    assert report.decisions[0].overall_status == "needs_verification"


@pytest.mark.parametrize("changes", [
    {"source_url": "https://invalid.example/notice.pdf"},
    {"source_url": "https://[broken"},
    {"source_sha256": "0" * 64},
])
def test_invalid_source_registry_cannot_be_used_even_for_real_quotation(source_candidate, changes):
    candidate = source_candidate.model_copy(update=changes)
    report = validate_eligibility_report(draft(candidate, requirement("applicant_type", candidate, "nonprofit organizations")), inputs(candidate))
    assert check(report, "applicant_type").status == "needs_verification"
    assert not check(report, "applicant_type").citations


def test_missing_and_invented_candidates_preserve_exact_input_coverage(source_candidate):
    invented = EligibilityDraft(decisions=[CandidateDraft(opportunity_id=999999, requirements=[])])
    report = validate_eligibility_report(invented, inputs(source_candidate))
    assert [item.opportunity_id for item in report.decisions] == [363696]
    assert len(report.decisions[0].requirements) == 8
    assert {item.code for item in report.validation_issues} >= {"unknown_candidate", "candidate_coverage"}


def test_unknown_status_or_schema_never_publishes_unvalidated_claim(source_candidate):
    malformed = {"decisions": [{"opportunity_id": 363696, "overall_status": "eligible", "requirements": []}]}
    report = validate_eligibility_report(malformed, inputs(source_candidate))
    assert all(item.status == "needs_verification" for item in report.decisions[0].requirements)
    assert any(issue.code == "draft_schema_invalid" for issue in report.validation_issues)


def test_report_questions_are_capped_but_all_eight_checks_remain_visible(source_candidate):
    report = validate_eligibility_report(draft(source_candidate), inputs(source_candidate))
    rendered = render_eligibility_report(report)
    questions = rendered.split("**Questions to resolve**", 1)[1]
    assert questions.count("\n- ") == 3
    assert len(report.decisions[0].requirements) == 8
    assert "planned" in questions or "plan to apply" in questions


def test_empty_input_is_not_claimed_to_mean_no_matching_grants(source_candidate):
    data = inputs(source_candidate).model_copy(update={"candidates": []})
    report = validate_eligibility_report(EligibilityDraft(), data)
    assert report.decisions == []
    assert "does not establish" in report.summary


def test_input_candidate_limit_and_unique_identity_are_enforced(source_candidate):
    data = inputs(source_candidate).model_dump()
    data["candidates"] = [source_candidate.model_dump()] * 2
    with pytest.raises(ValidationError, match="duplicate opportunities"):
        AnalystInput.model_validate(data)
    data["candidates"] *= 2
    with pytest.raises(ValidationError):
        AnalystInput.model_validate(data)
