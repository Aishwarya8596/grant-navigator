"""Validate a critic's review of the current, source-checked eligibility report."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from .eligibility import (
    AnalystInput, CandidateDraft, CandidateEvidence, EligibilityDraft, EligibilityReport,
    EvidenceReference, PROFILE_FIELDS, RULE_IDS, RequirementAssessment, RequirementDraft,
    RuleId, ValidationIssue, generation_schema, notice_source_registry,
    resolve_notice_references, validate_eligibility_report,
)


Verdict = Literal["approve", "revise"]
FindingKind = Literal["wrong_condition", "overlooked_evidence", "unsupported_claim", "coverage"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposedFinding(_Contract):
    rule_id: RuleId
    kind: FindingKind
    correction: str = Field(min_length=1, max_length=600)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=4)

    @field_validator("correction")
    @classmethod
    def require_instruction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A finding must identify a correction.")
        return value.strip()


class CandidateReview(_Contract):
    opportunity_id: StrictInt = Field(ge=1)
    reviewed_rule_ids: list[RuleId] = Field(min_length=1, max_length=len(RULE_IDS))
    findings: list[ProposedFinding] = Field(max_length=len(RULE_IDS))


class CriticDraft(_Contract):
    verdict: Verdict
    reviews: list[CandidateReview] = Field(min_length=1, max_length=3)


class CriticFinding(ProposedFinding):
    opportunity_id: int
    origin: Literal["critic", "validator"]


class CriticReview(_Contract):
    verdict: Verdict
    findings: list[CriticFinding]


def critic_generation_schema() -> dict:
    schema = generation_schema(CriticDraft)
    # A live model returned approve with reviews=[] when only the application
    # required coverage. State the nonempty collection in the wire schema too.
    schema["properties"]["reviews"]["minItems"] = 1
    return schema


# These are repairable defects in the analyst's submission. A missing user
# fact or unavailable notice is already a useful resolution when presented as
# unknown. It gives the reviewer no reason to demand another generation.
_COVERAGE_CODES = {"missing_or_duplicate_requirement", "candidate_coverage", "draft_schema_invalid"}
_REFERENCE_CODES = {
    "unknown_evidence_reference", "unsupported_quote", "missing_cited_support",
    "unknown_profile_field", "missing_profile_reference",
}


def _required_correction(row, candidate: CandidateEvidence, inputs, issues, registry):
    if issues & _COVERAGE_CODES:
        return "coverage", "Supply one explicit assessment of this rule, leaving unsupported facts unresolved."
    if issues & _REFERENCE_CODES:
        return "unsupported_claim", "Repair the profile or notice reference, or explicitly leave the check unresolved."
    if row.citations:
        refs = [EvidenceReference(evidence_id=c.evidence_id, quote=c.quote) for c in row.citations]
        resolved, error = resolve_notice_references(refs, candidate, registry)
        if error or resolved != row.citations:
            return "unsupported_claim", "Use a quotation, page and source belonging to this opportunity."
    if row.status == "needs_verification":
        return None
    if row.rule_id == "deadline":
        return "unsupported_claim", "Report the general date and leave the applicant-specific deadline unresolved."
    if row.rule_id == "source_currentness":
        if not candidate.currentness_verified or not candidate.notice_review_complete:
            return "unsupported_claim", "Keep the notice's version and completeness unresolved."
        return None
    if not row.citations or any(getattr(inputs.profile, name, None) is None for name in PROFILE_FIELDS[row.rule_id]):
        return "unsupported_claim", "Use stated profile facts and quoted rule evidence, or leave the check unresolved."
    return None


def _can_resolve_check(inputs, candidate, finding):
    """Use the analyst's existing rule checks to see if this quote can change an unknown."""
    fields = list(PROFILE_FIELDS[finding.rule_id])
    if finding.rule_id == "cost_sharing" and inputs.profile.americorps_grant_type == "cost_reimbursement":
        fields.append("can_meet_match")
    single = inputs.model_copy(update={"candidates": [candidate]})
    for status in ("met", "not_met"):
        row = RequirementDraft(rule_id=finding.rule_id, status=status, profile_fields=fields,
                               evidence_refs=finding.evidence_refs)
        draft = EligibilityDraft(decisions=[
            CandidateDraft(opportunity_id=candidate.opportunity.opportunity_id, requirements=[row])
        ])
        checked = validate_eligibility_report(draft, single)
        result = next(item for item in checked.decisions[0].requirements if item.rule_id == finding.rule_id)
        if result.status != "needs_verification":
            return True
    return False


def _check_finding(proposed, row, candidate, inputs, required, registry):
    resolved, error = resolve_notice_references(proposed.evidence_refs, candidate, registry)
    if error:
        raise ValueError(f"The critic supplied an invalid reference for {row.rule_id}: {error}.")
    if proposed.kind == "coverage":
        if required is None or required[0] != "coverage":
            raise ValueError("A coverage finding requires an omitted or duplicate assessment.")
    elif proposed.kind == "overlooked_evidence":
        if not resolved or row.status != "needs_verification" or not _can_resolve_check(inputs, candidate, proposed):
            raise ValueError("The proposed evidence and stated facts cannot resolve this overlooked check.")
    elif proposed.kind == "wrong_condition":
        if not resolved or (row.status == "needs_verification" and not row.citations):
            raise ValueError("A wrong-condition finding requires source evidence and a finding or citation to challenge.")
    elif required is None and (not resolved or row.status == "needs_verification"):
        raise ValueError("An unsupported-claim finding requires a demonstrated gap or verifiable counterevidence.")
    return CriticFinding(
        opportunity_id=candidate.opportunity.opportunity_id, origin="critic",
        rule_id=proposed.rule_id, kind=proposed.kind, correction=proposed.correction,
        evidence_refs=[EvidenceReference(evidence_id=item.evidence_id, quote=item.quote) for item in resolved],
    )


def _complete_ids(observed, expected):
    values = list(observed)
    return len(values) == len(expected) and set(values) == set(expected)


def validate_critic_review(raw: dict, inputs: AnalystInput, report: EligibilityReport) -> CriticReview:
    """Return actionable, source-bound feedback, or raise for unusable review output.

    The model reviews meaning. This boundary checks scope, coverage and source
    references and records independently identifiable defects with their origin.
    Approval refers only to the supplied assessment of the supplied excerpts.
    """
    draft = CriticDraft.model_validate(raw)
    if (report.invocation_id, report.profile_version, report.as_of_date) != (
        inputs.invocation_id, inputs.profile_version, inputs.as_of_date
    ):
        raise ValueError("The critic must review the current profile and invocation.")
    candidates = {item.opportunity.opportunity_id: item for item in inputs.candidates}
    decisions = {item.opportunity_id: item for item in report.decisions}
    if not candidates or not _complete_ids((item.opportunity_id for item in report.decisions), candidates):
        raise ValueError("The report must contain exactly the supplied candidates.")
    if not _complete_ids((item.opportunity_id for item in draft.reviews), candidates):
        raise ValueError("The critic must review each candidate once.")
    if (draft.verdict == "revise") != any(item.findings for item in draft.reviews):
        raise ValueError("The critic verdict is inconsistent with its findings.")

    findings = []
    for review in draft.reviews:
        oid = review.opportunity_id
        candidate = candidates[oid]
        decision = decisions[oid]
        if not _complete_ids(review.reviewed_rule_ids, RULE_IDS) or not _complete_ids(
            (row.rule_id for row in decision.requirements), RULE_IDS
        ):
            raise ValueError("Each candidate review and report must cover each of the eight checks exactly once.")
        proposed = {item.rule_id: item for item in review.findings}
        if len(proposed) != len(review.findings):
            raise ValueError("Combine feedback into one correction per targeted rule.")
        registry = notice_source_registry(candidate)
        for row in decision.requirements:
            codes = {issue.code for issue in report.validation_issues
                     if issue.opportunity_id in (oid, None) and issue.rule_id in (row.rule_id, None)}
            required = _required_correction(row, candidate, inputs, codes, registry)
            if row.rule_id in proposed:
                findings.append(_check_finding(proposed[row.rule_id], row, candidate, inputs, required, registry))
            elif required:
                kind, correction = required
                findings.append(CriticFinding(opportunity_id=oid, rule_id=row.rule_id, origin="validator",
                                               kind=kind, correction=correction))
    return CriticReview(verdict="revise" if findings else "approve", findings=findings)


def apply_unresolved_findings(report: EligibilityReport, findings: list[CriticFinding]) -> EligibilityReport:
    """Withhold each disputed finding and any overall block derived from it."""
    result = report.model_copy(deep=True)
    disputed = {(item.opportunity_id, item.rule_id) for item in findings}
    for decision in result.decisions:
        for index, row in enumerate(decision.requirements):
            if (decision.opportunity_id, row.rule_id) not in disputed:
                continue
            decision.requirements[index] = RequirementAssessment(
                rule_id=row.rule_id, status="needs_verification", applicability="uncertain",
                reason="The review left this requirement unresolved.",
                profile_fields=row.profile_fields, follow_up_question=row.follow_up_question,
                required_action="Check this requirement against the applicable notice and the applicant's facts.",
            )
            result.validation_issues.append(ValidationIssue(
                code="unresolved_critic_finding", opportunity_id=decision.opportunity_id,
                rule_id=row.rule_id, message="This requirement still has an outstanding correction.",
            ))
            if row.rule_id == "grant_type" and decision.blocking_scope == "selected_grant_type":
                decision.overall_status = "needs_verification"
                decision.blocking_scope = None
                decision.blocking_reasons = []
                decision.summary = "The selected grant type still needs verification."
    return result
