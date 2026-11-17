"""Check which independent critic findings can trigger a targeted revision."""

import pytest

from grant_navigator.critic import apply_unresolved_findings, validate_critic_review
from grant_navigator.eligibility import RULE_IDS, validate_eligibility_report
from test_eligibility import (
    NEW_QUOTE, SAM_QUOTE, check, draft, inputs, reference, requirement, source_candidate,
)


def critique(candidate, *findings):
    return {
        "verdict": "revise" if findings else "approve",
        "reviews": [{"opportunity_id": candidate.opportunity.opportunity_id,
                     "reviewed_rule_ids": list(RULE_IDS), "findings": list(findings)}],
    }


def objection(candidate, rule, kind, quote=None):
    return {"rule_id": rule, "kind": kind, "correction": f"Recheck the cited condition for {rule}.",
            "evidence_refs": [reference(candidate, quote).model_dump()] if quote else []}


def test_critic_can_approve_well_stated_unknowns_with_or_without_a_notice(source_candidate):
    for candidate in (source_candidate, source_candidate.model_copy(update={"notice_status": "notice_unavailable", "excerpts": []})):
        data = inputs(candidate)
        report = validate_eligibility_report(draft(candidate), data)
        review = validate_critic_review(critique(candidate), data, report)
        assert review.verdict == "approve" and review.findings == []
        assert report.confirmed_eligible is False


def test_mechanical_source_and_coverage_defects_override_an_approval(source_candidate):
    data = inputs(source_candidate)
    proposed = draft(source_candidate, requirement("applicant_type", source_candidate, "nonprofit organizations;"))
    rows = proposed.decisions[0].requirements
    rows[0].evidence_refs[0].quote = "This invented rule guarantees funding."
    rows.pop(-1)
    report = validate_eligibility_report(proposed, data)
    review = validate_critic_review(critique(source_candidate), data, report)
    assert review.verdict == "revise"
    assert {(item.rule_id, item.kind, item.origin) for item in review.findings} == {
        ("applicant_type", "unsupported_claim", "validator"), ("source_currentness", "coverage", "validator"),
    }
    assert all(item.evidence_refs == [] for item in review.findings)


@pytest.mark.parametrize("bad", ["empty", "omitted opportunity", "duplicate opportunity", "unknown opportunity",
                                  "missing rule", "duplicate rule", "contradictory approval", "empty revision",
                                  "unknown field", "source URL"])
def test_invalid_or_incomplete_review_cannot_approve_or_request_revision(source_candidate, bad):
    data = inputs(source_candidate)
    report = validate_eligibility_report(draft(source_candidate), data)
    raw = critique(source_candidate)
    review = raw["reviews"][0]
    if bad == "empty":
        raw = {}
    elif bad == "omitted opportunity":
        raw["reviews"].clear()
    elif bad == "duplicate opportunity":
        raw["reviews"].append(review)
    elif bad == "unknown opportunity":
        review["opportunity_id"] = 999999
    elif bad == "missing rule":
        review["reviewed_rule_ids"].pop()
    elif bad == "duplicate rule":
        review["reviewed_rule_ids"][-1] = "uei"
    elif bad == "contradictory approval":
        review["findings"].append(objection(source_candidate, "sam_registration", "coverage"))
    elif bad == "empty revision":
        raw["verdict"] = "revise"
    elif bad == "unknown field":
        raw["approved_for_award"] = True
    elif bad == "source URL":
        raw = critique(source_candidate, objection(source_candidate, "sam_registration", "overlooked_evidence", SAM_QUOTE))
        raw["reviews"][0]["findings"][0]["evidence_refs"][0]["citation_url"] = "https://invented.example"
    with pytest.raises(ValueError):
        validate_critic_review(raw, data, report)


@pytest.mark.parametrize("change", ["invocation", "profile", "date", "report coverage"])
def test_a_review_only_applies_to_current_assessment(source_candidate, change):
    data = inputs(source_candidate)
    report = validate_eligibility_report(draft(source_candidate), data)
    if change == "invocation":
        report.invocation_id += "-stale"
    elif change == "profile":
        report.profile_version += 1
    elif change == "date":
        report.as_of_date = report.as_of_date.replace(year=2025)
    else:
        report.decisions[0].requirements.pop(-1)
    with pytest.raises(ValueError):
        validate_critic_review(critique(source_candidate), data, report)


@pytest.mark.parametrize("problem", ["wrong quote", "wrong opportunity", "irrelevant quote", "missing fact",
                                     "missing notice", "wrong absence claim", "spurious coverage"])
def test_invalid_critic_feedback_never_changes_findings(source_candidate, problem):
    candidate = source_candidate
    if problem == "missing notice":
        candidate = candidate.model_copy(update={"notice_status": "notice_unavailable", "excerpts": []})
    data = inputs(candidate, sam_registration_active=None if problem == "missing fact" else True)
    report = validate_eligibility_report(draft(candidate), data)
    finding = objection(source_candidate, "sam_registration", "overlooked_evidence", SAM_QUOTE)
    if problem == "wrong quote":
        finding["evidence_refs"][0]["quote"] = "All organizations automatically have active registration."
    elif problem == "wrong opportunity":
        finding["evidence_refs"][0]["evidence_id"] = finding["evidence_refs"][0]["evidence_id"].replace("363696", "999999")
    elif problem == "irrelevant quote":
        finding["evidence_refs"] = [reference(source_candidate, NEW_QUOTE).model_dump()]
    elif problem in {"spurious coverage", "wrong absence claim"}:
        finding["evidence_refs"] = []
        finding["kind"] = "coverage" if problem == "spurious coverage" else "unsupported_claim"
    with pytest.raises(ValueError):
        validate_critic_review(critique(candidate, finding), data, report)


def test_genuine_overlooked_evidence_and_grounded_condition_challenge(source_candidate):
    data = inputs(source_candidate, sam_registration_active=True)
    data.profile.organization_type = "Volunteer group considering forming a nonprofit"
    report = validate_eligibility_report(draft(source_candidate,
        requirement("applicant_type", source_candidate, "nonprofit organizations;"),
    ), data)
    assert check(report, "applicant_type").status == "met"
    a = objection(source_candidate, "applicant_type", "wrong_condition", "nonprofit organizations;")
    a["correction"] = "The organization is considering forming a nonprofit. Its current applicant category remains unknown."
    b = objection(source_candidate, "sam_registration", "overlooked_evidence", SAM_QUOTE)
    review = validate_critic_review(critique(source_candidate, a, b), data, report)
    assert review.verdict == "revise" and all(item.origin == "critic" for item in review.findings)
    assert {item.rule_id for item in review.findings} == {"applicant_type", "sam_registration"}
    assert check(report, "sam_registration").status == "needs_verification"


def test_withholding_a_disputed_block_clears_decision_and_preserves_independent_rows(source_candidate):
    data = inputs(source_candidate, americorps_new_applicant=True, americorps_grant_type="full_cost_fixed_amount")
    report = validate_eligibility_report(draft(source_candidate,
        requirement("applicant_type", source_candidate, "nonprofit organizations;"),
        requirement("grant_type", source_candidate, NEW_QUOTE, "not_met"),
    ), data)
    review = validate_critic_review(critique(source_candidate,
        objection(source_candidate, "grant_type", "wrong_condition", NEW_QUOTE)
    ), data, report)
    safe = apply_unresolved_findings(report, review.findings)
    assert report.decisions[0].blocking_scope == "selected_grant_type"
    assert safe.decisions[0].blocking_scope is None and safe.decisions[0].blocking_reasons == []
    assert safe.decisions[0].overall_status == "needs_verification"
    assert check(safe, "grant_type").status == "needs_verification" and check(safe, "grant_type").citations == []
    assert check(safe, "applicant_type") == check(report, "applicant_type")
    assert safe.confirmed_eligible is False
