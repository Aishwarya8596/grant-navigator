"""Typed, conservative assessments of stated facts against notice excerpts.

The analyst proposes checks. This boundary resolves source references itself,
rejects unsupported claims, and never emits a confirmed-eligible outcome.
Citation integrity is not a complete semantic or legal review; critic review
and broader domain evaluation remain separate work.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .opportunities import GeneralDeadlineCheck, OpportunityRecord, check_general_deadline
from .profile import NonprofitProfile
from .tools.notices import NoticeExcerpt


RuleId = Literal[
    "applicant_type", "application_route", "sam_registration", "uei",
    "grant_type", "cost_sharing", "deadline", "source_currentness",
]
RuleStatus = Literal["met", "not_met", "needs_verification"]
Applicability = Literal["applies", "does_not_apply", "uncertain"]
RULE_IDS: tuple[RuleId, ...] = (
    "applicant_type", "application_route", "sam_registration", "uei",
    "grant_type", "cost_sharing", "deadline", "source_currentness",
)
RULE_LABELS = {
    "applicant_type": "Applicant type", "application_route": "Application route",
    "sam_registration": "SAM registration", "uei": "Valid UEI",
    "grant_type": "Grant type", "cost_sharing": "Cost sharing",
    "deadline": "Applicable deadline", "source_currentness": "Notice version and completeness",
}
PROFILE_FIELDS = {
    "applicant_type": ["organization_type"],
    "application_route": ["service_area", "planned_submission_route"],
    "sam_registration": ["sam_registration_active"],
    "uei": ["has_valid_uei"],
    "grant_type": ["americorps_grant_type", "americorps_new_applicant"],
    "cost_sharing": ["americorps_grant_type"],
    "deadline": [], "source_currentness": [],
}
QUESTIONS = {
    "applicant_type": "What type of organization will apply?",
    "application_route": "Where will the project operate, and do you plan to apply through a state commission or directly?",
    "sam_registration": "Is your organization's SAM registration active?",
    "uei": "Does your organization have a valid Unique Entity Identifier (UEI)?",
    "grant_type": "Which AmeriCorps grant type are you considering, and is this a new AmeriCorps applicant?",
    "cost_sharing": "Which grant type are you considering, and can you meet any matching requirement that applies to it?",
    "deadline": "What is the current applicant-specific deadline for your confirmed submission route?",
    "source_currentness": "Has the current official notice and any amendment been checked, including all mandatory requirements?",
}
ACTIONS = {
    "applicant_type": "Confirm the applicant category in the applicable notice.",
    "application_route": "Confirm the project service area and the applicable submission route before applying.",
    "sam_registration": "Check registration status and complete any required registration before submission; suggested processing time is not an extra deadline.",
    "uei": "Confirm a valid UEI before submission if required by the applicable notice.",
    "grant_type": "Confirm the selected grant mechanism and the applicant's new or returning status.",
    "cost_sharing": "Confirm the grant mechanism before assessing its matching requirement.",
    "deadline": "Check the latest deadline for the selected route, including any earlier commission deadline and exact due time.",
    "source_currentness": "Check the latest official notice, amendments, and complete mandatory requirement list.",
}
_FIXED_TYPES = {"full_cost_fixed_amount", "education_award_program", "professional_corps"}


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateEvidence(_Contract):
    opportunity: OpportunityRecord
    notice_status: str
    currentness_verified: bool = False
    notice_review_complete: bool = False
    source_sha256: str | None = None
    source_url: str | None = None
    snapshot_captured_at_utc: str | None = None
    excerpts: list[NoticeExcerpt] = Field(default_factory=list)


class AnalystInput(_Contract):
    profile: NonprofitProfile
    candidates: list[CandidateEvidence] = Field(max_length=3)
    as_of_date: date
    invocation_id: str = Field(min_length=1)
    profile_version: int = Field(ge=1)

    @model_validator(mode="after")
    def unique_candidates(self):
        ids = [candidate.opportunity.opportunity_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("analyst input must not contain duplicate opportunities")
        return self


class EvidenceReference(_Contract):
    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=1400)


class RequirementDraft(_Contract):
    rule_id: RuleId
    status: RuleStatus
    reason: str = Field(default="", max_length=2000)
    profile_fields: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=12)
    follow_up_question: str | None = Field(default=None, max_length=500)
    required_action: str | None = Field(default=None, max_length=1000)
    applicability: Applicability = "applies"


class FitEvidence(_Contract):
    dimension: Literal["purpose", "beneficiaries", "service_area", "timing"]
    assessment: Literal["supports", "conflicts"]
    synopsis_quote: str = Field(min_length=8, max_length=1400)


class CandidateDraft(_Contract):
    fit_evidence: list[FitEvidence] = Field(default_factory=list, max_length=4)
    # Google's response-schema adapter supports minimum, not exclusiveMinimum.
    opportunity_id: int = Field(ge=1)
    requirements: list[RequirementDraft] = Field(default_factory=list, max_length=16)
    summary: str = Field(default="", max_length=2000)


class EligibilityDraft(_Contract):
    decisions: list[CandidateDraft] = Field(default_factory=list, max_length=6)
    summary: str = Field(default="", max_length=2000)


def generation_schema(model_type: type[BaseModel]) -> dict:
    """Expose the contract through Gemini's narrower responseSchema dialect.

    Keep generation focused on shape and enums; the SDK and remote API differ
    in the constraints they accept. The application-side EligibilityDraft
    still enforces bounds and extra='forbid'. A simpler generation schema never
    relaxes acceptance of the result.
    """
    def compatible(value):
        if isinstance(value, dict):
            omitted = {"additionalProperties", "title", "default", "minLength", "maxLength", "minItems", "maxItems"}
            return {key: compatible(item) for key, item in value.items() if key not in omitted}
        if isinstance(value, list):
            return [compatible(item) for item in value]
        return value

    return compatible(model_type.model_json_schema())


def analyst_generation_schema() -> dict:
    schema = generation_schema(EligibilityDraft)
    # The coordinator renders summaries from validated findings. Skip optional
    # model summaries on the wire, keeping older stored drafts readable.
    schema["properties"].pop("summary")
    candidate = schema["$defs"]["CandidateDraft"]
    candidate["properties"].pop("summary")
    candidate["required"].append("fit_evidence")
    return schema


class ResolvedCitation(_Contract):
    evidence_id: str
    quote: str
    page_number: int
    citation_url: str
    source_sha256: str
    snapshot_captured_at_utc: str | None = None


class ValidationIssue(_Contract):
    code: str
    message: str
    opportunity_id: int | None = None
    rule_id: RuleId | None = None


class RequirementAssessment(_Contract):
    rule_id: RuleId
    status: RuleStatus
    reason: str
    applicability: Applicability = "uncertain"
    profile_fields: list[str] = Field(default_factory=list)
    citations: list[ResolvedCitation] = Field(default_factory=list)
    follow_up_question: str | None = None
    required_action: str | None = None


class CandidateDecision(_Contract):
    opportunity_id: int
    opportunity_number: str | None = None
    title: str | None = None
    source_page: str
    overall_status: Literal["needs_verification", "blocking_issue"]
    requirements: list[RequirementAssessment]
    blocking_reasons: list[str] = Field(default_factory=list)
    blocking_scope: Literal["selected_grant_type"] | None = None
    general_deadline: GeneralDeadlineCheck
    summary: str


class EligibilityReport(_Contract):
    invocation_id: str
    profile_version: int
    as_of_date: date
    decisions: list[CandidateDecision]
    summary: str
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    semantic_review_complete: Literal[False] = False
    confirmed_eligible: Literal[False] = False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _field(profile: NonprofitProfile, name: str):
    return getattr(profile, name, None)


def notice_source_registry(candidate: CandidateEvidence) -> dict[str, NoticeExcerpt]:
    """Use only the candidate's trusted tool-supplied source registry."""
    if candidate.notice_status != "success" or not candidate.excerpts:
        return {}
    digest, url = candidate.source_sha256, candidate.source_url
    if not digest or not re.fullmatch(r"[a-f0-9]{64}", digest) or not url:
        return {}
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme == "https" and parsed.hostname
            and parsed.hostname.casefold().endswith(".gov")
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment
        )
    except ValueError:
        return {}
    if not valid_url:
        return {}
    registry = {}
    for excerpt in candidate.excerpts:
        prefix = f"notice:{candidate.opportunity.opportunity_id}:{digest[:16]}:p{excerpt.page_number}:c"
        expected_url = f"{url}#page={excerpt.page_number}"
        if excerpt.evidence_id.startswith(prefix) and excerpt.citation_url == expected_url:
            if excerpt.evidence_id in registry:
                return {}  # Ambiguous identifiers must not resolve to arbitrary text.
            registry[excerpt.evidence_id] = excerpt
    return registry


def resolve_notice_references(
    references: list[EvidenceReference],
    candidate: CandidateEvidence,
    registry: dict[str, NoticeExcerpt],
) -> tuple[list[ResolvedCitation], str | None]:
    resolved = []
    seen = set()
    for reference in references:
        excerpt = registry.get(reference.evidence_id)
        if excerpt is None:
            return [], "unknown_evidence_reference"
        quote = _normalize(reference.quote)
        if not quote or quote not in _normalize(excerpt.text):
            return [], "unsupported_quote"
        key = (reference.evidence_id, quote)
        if key not in seen:
            resolved.append(ResolvedCitation(
                evidence_id=reference.evidence_id, quote=quote,
                page_number=excerpt.page_number,
                citation_url=f"{candidate.source_url}#page={excerpt.page_number}",
                source_sha256=candidate.source_sha256,
                snapshot_captured_at_utc=candidate.snapshot_captured_at_utc,
            ))
            seen.add(key)
    return resolved, None


def _unknown(rule_id: RuleId, reason: str, citations=None, profile_fields=None) -> RequirementAssessment:
    return RequirementAssessment(
        rule_id=rule_id, status="needs_verification", reason=reason,
        applicability="uncertain", citations=citations or [],
        profile_fields=profile_fields or list(PROFILE_FIELDS[rule_id]),
        follow_up_question=QUESTIONS[rule_id], required_action=ACTIONS[rule_id],
    )


def _rule_context(rule: RuleId, citations: list[ResolvedCitation], registry: dict) -> str:
    # A valid reference to a page is insufficient if the quoted words do not
    # support this rule. Do not borrow mandatory language from elsewhere in
    # the surrounding passage to turn an advisory quotation into a condition.
    return " ".join(item.quote for item in citations).casefold()


def _new_full_cost_exclusion(text: str) -> bool:
    text = text.casefold()
    return (
        "new applicant" in text
        and ("full-cost fixed" in text or "full cost fixed" in text)
        and bool(re.search(r"(?:may not|cannot|can not|not eligible|ineligible)", text))
    )


def _assess(
    requirement: RequirementDraft | None,
    candidate: CandidateEvidence,
    profile: NonprofitProfile,
    registry: dict,
    rule: RuleId,
) -> tuple[RequirementAssessment, list[ValidationIssue], bool]:
    issues = []
    opportunity_id = candidate.opportunity.opportunity_id

    def unknown(reason: str, code: str | None = None, citations=None, fields=None):
        if code:
            issues.append(ValidationIssue(code=code, message=reason, opportunity_id=opportunity_id, rule_id=rule))
        return _unknown(rule, reason, citations, fields), issues, False

    if not registry:
        code = "notice_evidence_unavailable" if requirement and requirement.status != "needs_verification" else None
        assessment, source_issues, blocking = unknown("No accepted full-notice excerpts support this check. Retrieve the applicable notice before assessing it.", code)
        assessment.follow_up_question = f"Can the official full notice for opportunity {opportunity_id} be obtained and reviewed?"
        assessment.required_action = "Obtain and review the applicable official notice before applying any of these rule categories."
        return assessment, source_issues, blocking
    if requirement is None:
        return unknown("This requirement was not supported by a unique analyst check.", "missing_or_duplicate_requirement")
    citations, citation_error = resolve_notice_references(requirement.evidence_refs, candidate, registry)
    if citation_error:
        return unknown("The proposed source reference or quotation could not be verified against this opportunity's notice.", citation_error)
    if any(name not in type(profile).model_fields for name in requirement.profile_fields):
        return unknown("The proposed check referenced an unknown profile field.", "unknown_profile_field")

    if rule == "source_currentness":
        if not candidate.currentness_verified or not candidate.notice_review_complete:
            return unknown("The source is a dated or partial review; current amendments and the complete requirement list remain unverified.",
                           "source_not_current_or_complete" if requirement.status != "needs_verification" else None, citations)
        return RequirementAssessment(
            rule_id=rule, status="met", applicability="applies",
            reason="The trusted input marks the source current and its mandatory-requirement review complete.",
            citations=citations,
        ), issues, False

    if rule == "deadline":
        return unknown("The API and notice provide general deadline context, but the applicant-specific deadline and route have not been verified.",
                       "applicant_deadline_not_verified" if requirement.status != "needs_verification" else None, citations)

    fields = list(PROFILE_FIELDS[rule])
    mechanism = _field(profile, "americorps_grant_type")
    if rule == "cost_sharing" and mechanism == "cost_reimbursement":
        fields.append("can_meet_match")
    missing = [name for name in fields if _field(profile, name) is None]
    if rule == "grant_type" and mechanism == "fixed_amount_unspecified":
        missing.append("specific fixed-amount grant type")
    if rule == "cost_sharing" and mechanism == "fixed_amount_unspecified":
        missing.append("specific fixed-amount grant type")
    if missing:
        return unknown("Missing facts prevent this assessment: " + ", ".join(name.replace("_", " ") for name in missing) + ".",
                       "missing_profile_facts" if requirement.status != "needs_verification" else None, citations, fields)
    apply_known_condition = (
        rule == "grant_type" and mechanism == "full_cost_fixed_amount"
        and _field(profile, "americorps_new_applicant") is True
        or rule == "cost_sharing" and mechanism in _FIXED_TYPES
    )
    if requirement.status == "needs_verification" and not apply_known_condition:
        return unknown("The analyst left this requirement unresolved; the cited passages do not establish completion of the applicable check.", citations=citations, fields=fields)
    if not citations:
        return unknown("A finding requires a quotation from an accepted notice passage.", "missing_cited_support", fields=fields)
    if not set(fields).issubset(requirement.profile_fields):
        return unknown("The finding did not identify all profile facts needed for this rule.", "missing_profile_reference", citations, fields)

    context = _rule_context(rule, citations, registry)
    expected: RuleStatus | None = None
    reason = "The stated facts and cited notice passage support this limited requirement check; other requirements remain unresolved."
    applicability: Applicability = "applies"
    blocking = False

    if rule == "applicant_type":
        if not any(term in context for term in ("eligible", "applicants", "nonprofit", "non-profit")):
            return unknown("The cited passage does not identify an applicant-category rule.", "rule_not_supported", citations, fields)
        if requirement.status == "not_met":
            return unknown("An applicant-category exclusion needs a separately verified, explicit restriction; a category list alone is insufficient.", "unverified_applicant_exclusion", citations, fields)
        organization_type = str(_field(profile, "organization_type")).casefold()
        if re.search(r"\b(?:for[- ]profit|not (?:an? )?(?:registered )?(?:non[- ]?profit|501))", organization_type):
            return unknown("The stated organization type is contradictory or does not establish an affirmative nonprofit applicant category.", "applicant_category_uncertain", citations, fields)
        if re.search(r"501\s*\(\s*c\s*\)\s*\(?\s*4\s*\)?", organization_type):
            return unknown("This nonprofit category needs review of the notice's category-specific restrictions; the general nonprofit list alone is insufficient.", "applicant_category_uncertain", citations, fields)
        if re.search(r"non-?profit.{0,70}(?:not eligible|ineligible|may not apply)", context):
            return unknown("The quoted applicant-category wording may contain an exclusion; an affirmative match was not established.", "applicant_category_uncertain", citations, fields)
        if not (
            any(term in organization_type for term in ("501(c)(3)", "nonprofit", "non-profit"))
            and any(term in context for term in ("nonprofit", "non-profit"))
        ):
            return unknown("The applicant category cannot be matched conservatively from the available facts and passage.", "applicant_category_uncertain", citations, fields)
        expected = "met"
        reason = "The stated nonprofit organization type is supported by the cited applicant-category passage; this does not establish overall eligibility."

    elif rule == "application_route":
        if not any(term in context for term in ("apply through", "apply directly", "application route", "state commission", "state or territory commission")):
            return unknown("The cited passage does not support an application-route condition.", "rule_not_supported", citations, fields)
        # Do not derive geography or route compliance merely from headquarters.
        # The proposed interpretation remains limited by the explicit service
        # area and submission route, and is subject to later semantic review.
        planned = _field(profile, "planned_submission_route")
        area = str(_field(profile, "service_area")).casefold()
        explicit_multi_state = bool(re.search(
            r"\b(?:multi[- ]state|multiple states|more than one state|two states|several states)\b", area,
        ))
        explicit_single_state = not explicit_multi_state and (
            bool(re.search(r"\b(?:single[- ]state|one state)\b", area))
            or (
                "only" in area
                and not any(token in area for token in (" and ", ",", ";", "multiple", "more than one"))
            )
        )
        known_americorps_route = opportunity_id == 363696 and candidate.opportunity.opportunity_number == "AC-08-28-26"
        if requirement.status == "met" and planned == "direct" and explicit_single_state and known_americorps_route:
            return unknown("The stated single-state project and direct-submission plan require a verified route exception before this route can be marked met.", "unverified_route_exception", citations, fields)
        supports_commission = "commission" in context and "apply through" in context
        supports_direct = "apply directly" in context or "directly to americorps" in context
        if known_americorps_route:
            # Genuine quotations can still describe the wrong branch of a
            # conditional rule. Bind the quoted geography to the stated scope
            # before accepting either a positive or negative route finding.
            if explicit_multi_state:
                if "more than one state" not in context or not supports_direct:
                    return unknown("The quoted route condition does not establish the route for the stated multi-state project.", "route_condition_not_applicable", citations, fields)
                applicable_plan = "direct"
            elif explicit_single_state:
                if "only one state" not in context or not supports_commission:
                    return unknown("The quoted route condition does not establish the route for the stated single-state project.", "route_condition_not_applicable", citations, fields)
                if planned == "direct":
                    return unknown("A direct route for this single-state project requires checking an applicable exception.", "unverified_route_exception", citations, fields)
                applicable_plan = "state_commission"
            else:
                return unknown("Confirm whether the project is single-state or multi-state before applying the quoted route condition.", "project_scope_unverified", citations, fields)
            expected_route_status = "met" if planned == applicable_plan else "not_met"
            if requirement.status != expected_route_status:
                return unknown("The proposed route finding does not follow the condition applicable to the stated service area.", "profile_or_condition_conflict", citations, fields)
        supports_plan = supports_commission if planned == "state_commission" else supports_direct
        supports_other = supports_direct if planned == "state_commission" else supports_commission
        if (
            requirement.status == "met" and not supports_plan
            or requirement.status == "not_met" and not supports_other
        ):
            return unknown("The quoted route condition does not support the proposed finding for the stated planned route.", "profile_or_condition_conflict", citations, fields)
        expected = requirement.status
        reason = (
            "The stated project service area and planned route were compared with the cited route condition; exceptions and current instructions still require review."
            if expected == "met" else
            "The proposed submission route conflicts with the cited route condition for the stated service area; confirm the applicable route before submitting."
        )

    elif rule in ("sam_registration", "uei"):
        def supports_registration_condition(citation):
            # Do not combine a SAM help-link quote with mandatory UEI wording
            # in another sentence to invent an active-SAM requirement.
            for sentence in re.split(r"(?<=[.!?])\s+", citation.quote.casefold()):
                if not re.search(r"\b(?:must|required)\b", sentence):
                    continue
                if rule == "sam_registration":
                    if re.search(r"\b(?:active|valid)\s+sam\s+registration\b", sentence):
                        return True
                elif re.search(r"\bvalid\b", sentence) and re.search(r"\b(?:uei|unique entity identifier)\b", sentence):
                    return True
            return False

        if not any(supports_registration_condition(citation) for citation in citations):
            return unknown("The passage does not establish a mandatory registration requirement; suggested processing time is not an additional deadline.", "advisory_not_mandatory", citations, fields)
        fact = _field(profile, fields[0])
        expected = "met" if fact is True else "not_met"
        reason = (
            f"The profile states that {'SAM registration is active' if rule == 'sam_registration' else 'a valid UEI is held'}; the cited passage requires it."
            if expected == "met" else
            f"The profile states that {'SAM registration is not active' if rule == 'sam_registration' else 'a valid UEI is not held'}. This is a readiness gap to address, not an automatic exclusion from the funding opportunity."
        )

    elif rule == "grant_type":
        new_applicant = _field(profile, "americorps_new_applicant")
        quoted = " ".join(item.quote for item in citations).casefold()
        known_americorps = opportunity_id == 363696 and candidate.opportunity.opportunity_number == "AC-08-28-26"
        if mechanism == "full_cost_fixed_amount" and new_applicant is True:
            if not (known_americorps and any(item.page_number == 8 for item in citations) and _new_full_cost_exclusion(quoted)):
                return unknown("The selected-option exclusion lacks the exact scoped notice support required for a blocking finding.", "unverified_grant_type_exclusion", citations, fields)
            expected = "not_met"
            blocking = True
            reason = "The stated new-applicant status conflicts with the quoted restriction on full-cost fixed-amount grants. This blocks that selected grant type, not every grant type in the notice."
        elif mechanism == "full_cost_fixed_amount" and new_applicant is False and _new_full_cost_exclusion(context):
            expected = "met"
            applicability = "does_not_apply"
            reason = "The quoted new-applicant restriction does not apply to the stated returning-applicant status; other grant-type conditions remain unverified."
        else:
            aliases = {
                "cost_reimbursement": ("cost reimbursement", "cost-reimbursement"),
                "education_award_program": ("education award program", "eap"),
                "professional_corps": ("professional corps",),
            }
            if not any(term in context for term in aliases.get(mechanism, ())):
                return unknown("The cited passage does not support the selected grant mechanism.", "rule_not_supported", citations, fields)
            if requirement.status == "not_met":
                return unknown("No approved selected-option exclusion was established for this mechanism.", "unverified_grant_type_exclusion", citations, fields)
            expected = "met"
            reason = "The selected mechanism is named in the cited applicant/grant-type passage; other restrictions remain unverified."

    elif rule == "cost_sharing":
        fixed_no_match = (
            ("fixed amount" in context or "fixed-amount" in context)
            and ("no cost share" in context or "no matching requirement" in context)
        )
        if mechanism in _FIXED_TYPES:
            if not fixed_no_match:
                return unknown("The selected fixed-amount mechanism needs its own matching-rule passage; the API boolean alone is insufficient.", "conditional_matching_unverified", citations, fields)
            expected = "met"
            applicability = "does_not_apply"
            reason = "The cited notice states that fixed-amount grants have no cost-share or matching requirement. A blanket matching exclusion was not applied."
        elif mechanism == "cost_reimbursement":
            if not (
                ("cost reimbursement" in context or "cost-reimbursement" in context)
                and ("required to match" in context or "matching funds" in context or "must match" in context)
            ):
                return unknown("The cited passage does not establish the matching condition for cost-reimbursement grants.", "conditional_matching_unverified", citations, fields)
            expected = "met" if _field(profile, "can_meet_match") is True else "not_met"
            reason = (
                "The profile states that the applicable match can be met, and the cited cost-reimbursement passage requires a match."
                if expected == "met" else
                "The profile states that the applicable match cannot currently be met. This is a funding-readiness gap to resolve, not an automatic exclusion from every mechanism."
            )
        else:
            return unknown("The grant mechanism is not specific enough to apply a matching condition.", "conditional_matching_unverified", citations, fields)

    if expected != requirement.status and not blocking and applicability != "does_not_apply":
        return unknown("The proposed finding contradicts the stated profile facts or applicable condition.", "profile_or_condition_conflict", citations, fields)
    if expected != requirement.status and (blocking or applicability == "does_not_apply"):
        issues.append(ValidationIssue(
            code="scoped_grant_type_condition_applied" if blocking else "conditional_rule_corrected",
            message="A verified, limited source condition replaced the draft finding; it was not promoted to overall eligibility.",
            opportunity_id=opportunity_id, rule_id=rule,
        ))
    return RequirementAssessment(
        rule_id=rule, status=expected or "needs_verification", applicability=applicability,
        reason=reason, profile_fields=fields, citations=citations,
        required_action=ACTIONS[rule] if expected == "not_met" else None,
    ), issues, blocking


def validate_eligibility_report(
    draft: EligibilityDraft | dict | str,
    inputs: AnalystInput | dict,
) -> EligibilityReport:
    """Resolve proposals against trusted inputs, downgrading unsupported checks.

    This checks coverage, source identity, exact quotations, required facts,
    and a few explicit conditional rules. It does not establish complete
    semantic correctness or introduce an approval/confirmed-eligible status.
    """
    inputs = AnalystInput.model_validate(inputs)
    issues = []
    try:
        parsed = EligibilityDraft.model_validate_json(draft) if isinstance(draft, str) else EligibilityDraft.model_validate(draft)
    except ValidationError:
        parsed = EligibilityDraft()
        issues.append(ValidationIssue(code="draft_schema_invalid", message="The analyst output was not a valid structured assessment; unsupported checks remain unresolved."))
    known_ids = {item.opportunity.opportunity_id for item in inputs.candidates}
    grouped = {}
    for proposed in parsed.decisions:
        if proposed.opportunity_id not in known_ids:
            issues.append(ValidationIssue(code="unknown_candidate", message="An invented or unresearched opportunity was omitted from the accepted report.", opportunity_id=proposed.opportunity_id))
            continue
        grouped.setdefault(proposed.opportunity_id, []).append(proposed)

    decisions = []
    for candidate in inputs.candidates:
        opportunity = candidate.opportunity
        proposals = grouped.get(opportunity.opportunity_id, [])
        if len(proposals) != 1:
            issues.append(ValidationIssue(code="candidate_coverage", message="A missing or duplicate candidate assessment was replaced with unresolved checks.", opportunity_id=opportunity.opportunity_id))
        proposal = proposals[0] if len(proposals) == 1 else None
        requirements = {}
        for check in proposal.requirements if proposal else []:
            requirements.setdefault(check.rule_id, []).append(check)
        registry = notice_source_registry(candidate)
        accepted, blocking = [], False
        for rule in RULE_IDS:
            proposed = requirements.get(rule, [])
            assessment, check_issues, blocks = _assess(
                proposed[0] if len(proposed) == 1 else None,
                candidate, inputs.profile, registry, rule,
            )
            accepted.append(assessment)
            issues.extend(check_issues)
            blocking |= blocks
        blocking_reasons = [item.reason for item in accepted if item.rule_id == "grant_type" and item.status == "not_met"] if blocking else []
        decisions.append(CandidateDecision(
            opportunity_id=opportunity.opportunity_id,
            opportunity_number=opportunity.opportunity_number,
            title=opportunity.title, source_page=opportunity.source_page,
            overall_status="blocking_issue" if blocking else "needs_verification",
            requirements=accepted, blocking_reasons=blocking_reasons,
            blocking_scope="selected_grant_type" if blocking else None,
            general_deadline=check_general_deadline(opportunity, inputs.as_of_date),
            summary=(
                "The selected grant-type option conflicts with the cited new-applicant restriction; other options and overall eligibility remain unverified."
                if blocking else
                "The opportunity needs further verification. Requirement checks reflect stated facts and selected notice passages, not a final eligibility decision."
            ),
        ))
    return EligibilityReport(
        invocation_id=inputs.invocation_id, profile_version=inputs.profile_version,
        as_of_date=inputs.as_of_date, decisions=decisions,
        summary=(f"Assessed {len(decisions)} researched {'opportunity' if len(decisions) == 1 else 'opportunities'}; eligibility remains unconfirmed."
                 if decisions else "No researched opportunities were supplied for analysis; this does not establish that no matching grants exist."),
        validation_issues=issues,
    )


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _follow_up_questions(decision: CandidateDecision) -> list[str]:
    unresolved = {item.rule_id: item for item in decision.requirements if item.follow_up_question}
    unique = list(dict.fromkeys(item.follow_up_question for item in unresolved.values()))
    if len(unique) <= 1:
        return unique
    questions = []
    if "application_route" in unresolved:
        questions.append(QUESTIONS["application_route"])
    if "grant_type" in unresolved or "cost_sharing" in unresolved:
        questions.append("Which grant type are you considering, is this a new applicant, and can any applicable matching requirement be met?")
    if "sam_registration" in unresolved or "uei" in unresolved:
        questions.append("Is SAM registration active, and does the organization have a valid UEI?")
    for rule in ("applicant_type", "deadline", "source_currentness"):
        if rule in unresolved:
            questions.append(QUESTIONS[rule])
    return list(dict.fromkeys(questions))[:3]


def render_eligibility_report(report: EligibilityReport | dict) -> str:
    """Render accepted checks with resolver-produced links, never draft URLs."""
    report = EligibilityReport.model_validate(report)
    lines = ["## Eligibility assessment", "", f"Assessment date: {report.as_of_date.isoformat()}.", "", report.summary]
    for decision in report.decisions:
        label = decision.opportunity_number or str(decision.opportunity_id)
        lines += ["", f"### {_cell(decision.title or label)}", "",
                  f"Opportunity: [{_cell(label)}]({decision.source_page})", "",
                  f"**Overall finding: {'Selected grant-type conflict' if decision.overall_status == 'blocking_issue' else 'Needs verification'}**", "", decision.summary]
        deadline = decision.general_deadline
        if deadline.deadline_date:
            lines += ["", f"API general date: **{deadline.deadline_date.isoformat()}** ({deadline.status.replace('_', ' ')} relative to the assessment date). The applicant-specific deadline remains unverified."]
        lines += ["", "| Requirement | Finding | Basis |", "|---|---|---|"]
        actions = []
        for requirement in decision.requirements:
            label_status = (
                "Not applicable to this condition" if requirement.applicability == "does_not_apply"
                else {"met": "Met on stated facts", "not_met": "Not met / action needed", "needs_verification": "Needs verification"}[requirement.status]
            )
            links = " ".join(dict.fromkeys(f"[PDF p. {item.page_number}]({item.citation_url})" for item in requirement.citations))
            lines.append(f"| {RULE_LABELS[requirement.rule_id]} | {label_status} | {_cell(requirement.reason)} {links} |")
            if requirement.status == "not_met" and requirement.required_action:
                actions.append(requirement.required_action)
        if decision.blocking_reasons:
            lines += ["", "**Selected-option issue:** " + " ".join(decision.blocking_reasons)]
        if actions:
            lines += ["", "**Actions to address**", "", *[f"- {action}" for action in dict.fromkeys(actions)]]
        questions = _follow_up_questions(decision)
        if questions:
            lines += ["", "**Questions to resolve**", "", *[f"- {question}" for question in dict.fromkeys(questions)]]
    lines += ["", "These checks use stated facts and selected notice evidence. Source completeness, current amendments, and overall eligibility still require verification."]
    return "\n".join(lines)
