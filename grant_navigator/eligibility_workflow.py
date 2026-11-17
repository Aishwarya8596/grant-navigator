"""Run the eligibility analyst and critic with the current research evidence."""

from __future__ import annotations

from datetime import datetime
import logging
import re
from zoneinfo import ZoneInfo

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest

from .critic import apply_unresolved_findings, validate_critic_review
from .eligibility import (
    RULE_IDS, AnalystInput, CandidateDraft, CandidateEvidence, EligibilityDraft,
    EligibilityReport, validate_eligibility_report,
)
from .opportunities import OpportunityRecord, normalize_opportunity
from .ranking import rank_candidates
from .profile import NonprofitProfile
from .tools.intake import (
    CRITIC_HISTORY_KEY, CRITIC_OUTCOME_KEY, ELIGIBILITY_OUTCOME_KEY, ELIGIBILITY_REPORT_KEY, PROFILE_KEY, PROFILE_VERSION_KEY,
    RANKING_KEY, RESEARCH_EVIDENCE_KEY, RESEARCH_OUTCOME_KEY,
)


logger = logging.getLogger(__name__)
ELIGIBILITY_RAW_KEY = "eligibility_raw"
ELIGIBILITY_INPUT_SCOPE_KEY = "eligibility_input_scope"
MAX_ANALYST_REVISIONS = 2


def build_analyst_input(context) -> AnalystInput:
    state = context.state
    evidence = state.get(RESEARCH_EVIDENCE_KEY) or {}
    if (
        evidence.get("invocation_id") != context.invocation_id
        or evidence.get("profile_version") != state.get(PROFILE_VERSION_KEY)
    ):
        raise ValueError("Current research evidence is required before eligibility analysis.")
    candidates = []
    for key, detail in evidence.get("details", {}).items():
        if detail.get("opportunity"):
            opportunity = OpportunityRecord.model_validate(detail["opportunity"])
        else:
            # Earlier saved/test records have only discovery identity fields.
            # Preserve their unknown facts rather than inventing new metadata.
            opportunity = normalize_opportunity({"status": "success", **detail})
        if str(opportunity.opportunity_id) != key:
            raise ValueError("Opportunity identity differs from the evidence registry.")
        notice = evidence.get("notices", {}).get(key) or {}
        candidates.append(CandidateEvidence(
            opportunity=opportunity,
            notice_status=notice.get("status", "not_reviewed"),
            currentness_verified=notice.get("currentness_verified") is True,
            notice_review_complete=False,
            source_sha256=notice.get("source_sha256"),
            source_url=notice.get("source_url"),
            snapshot_captured_at_utc=notice.get("snapshot_captured_at_utc"),
            excerpts=notice.get("excerpts", []),
        ))
    return AnalystInput(
        profile=NonprofitProfile.model_validate(state.get(PROFILE_KEY, {})),
        candidates=candidates,
        as_of_date=datetime.now(ZoneInfo("America/Los_Angeles")).date(),
        invocation_id=context.invocation_id,
        profile_version=state[PROFILE_VERSION_KEY],
    )


def begin_eligibility_analysis(callback_context: CallbackContext) -> None:
    """Only the analyst writes its raw-result key during the nested run."""
    callback_context.state[ELIGIBILITY_RAW_KEY] = None
    callback_context.state[ELIGIBILITY_INPUT_SCOPE_KEY] = {
        "invocation_id": callback_context.invocation_id,
        "profile_version": callback_context.state.get(PROFILE_VERSION_KEY),
    }
    return None


def _merge_revision(previous, patch, findings, inputs):
    """Change only the requested candidate/rule pairs, even if the model rewrote others."""
    targets = {(finding.opportunity_id, finding.rule_id) for finding in findings}

    def rows_by_rule(draft, opportunity_id):
        candidates = [item for item in draft.decisions if item.opportunity_id == opportunity_id]
        if len(candidates) != 1:
            return {}
        rows = {}
        for row in candidates[0].requirements:
            rows.setdefault(row.rule_id, []).append(row)
        return rows

    decisions = []
    for candidate in inputs.candidates:
        identity = candidate.opportunity.opportunity_id
        original = rows_by_rule(previous, identity)
        proposed = rows_by_rule(patch, identity)
        rows = []
        for rule in RULE_IDS:
            replacements = proposed.get(rule, [])
            if (identity, rule) in targets and len(replacements) == 1:
                rows.extend(replacements)
            else:
                rows.extend(original.get(rule, []))
        decisions.append(CandidateDraft(opportunity_id=identity, requirements=rows))
    return EligibilityDraft(decisions=decisions)


def _review_state(report: EligibilityReport):
    """Compare the finding, its basis and any validation gaps across revisions."""
    rows = {}
    for decision in report.decisions:
        for check in decision.requirements:
            key = (decision.opportunity_id, check.rule_id)
            rows[key] = (
                check.status, check.applicability,
                frozenset((ref.evidence_id, tuple(re.findall(r"\w+", ref.quote.casefold())))
                          for ref in check.citations),
                frozenset(issue.code for issue in report.validation_issues if
                          issue.opportunity_id == decision.opportunity_id and issue.rule_id in (None, check.rule_id)),
            )
    return rows


async def _run_draft(context, analyst, payload):
    result = await context.run_node(analyst, node_input=payload, use_sub_branch=True)
    if not isinstance(result, dict):
        raise ValueError("Missing structured analyst result.")
    return EligibilityDraft.model_validate(result)


async def _review_assessment(context, analyst, critic, inputs, draft, report):
    source = inputs.model_dump(mode="json")
    history = []
    pending = []
    previous_rows = {}
    revisions = 0
    status = "failed"
    candidate_ids = [item.opportunity.opportunity_id for item in inputs.candidates]
    assignment = (
        f"Review these {len(candidate_ids)} opportunities: {', '.join(map(str, candidate_ids))}. "
        "Return one reviews entry for every ID, including on approval. List every rule you checked "
        f"in reviewed_rule_ids: {', '.join(RULE_IDS)}. Only the findings array may be empty."
    )
    while True:
        entry = {
            "round": revisions + 1, "draft": draft.model_dump(mode="json"),
            "assessment": report.model_dump(mode="json"), "critic_draft": None, "review": None,
        }
        history.append(entry)
        try:
            review_input = {"assignment": assignment, "source_input": source, "assessment": entry["assessment"]}
            if pending:
                review_input["previous_objections"] = [item.model_dump(mode="json") for item in pending]
                review_input["assignment"] += " Recheck every previous objection against this revised assessment."
            raw = await context.run_node(
                critic, node_input=review_input,
                use_sub_branch=True,
            )
            entry["critic_draft"] = raw if isinstance(raw, dict) else None
            review = validate_critic_review(raw, inputs, report)
            rows = _review_state(report)
            requested = {(item.opportunity_id, item.rule_id) for item in review.findings}
            # A new approval cannot silently discard an earlier objection if
            # the affected finding and its supporting evidence never changed.
            carried = [item for item in pending
                       if (key := (item.opportunity_id, item.rule_id)) not in requested
                       and previous_rows[key] == rows[key]]
            if carried:
                review = review.model_copy(update={"verdict": "revise", "findings": [*review.findings, *carried]})
                entry["carried_forward"] = [item.model_dump(mode="json") for item in carried]
            entry["review"] = review.model_dump(mode="json")
            pending = review.findings
            previous_rows = rows
            if review.verdict == "approve":
                status = "approved"
                break
            if revisions == MAX_ANALYST_REVISIONS:
                status = "revision_limit"
                break
            revisions += 1
            revision_request = {"previous_assessment": entry["assessment"],
                                "requested_changes": [item.model_dump(mode="json") for item in pending]}
            patch = await _run_draft(context, analyst, {**source, "revision": revision_request})
            entry["revision_draft"] = patch.model_dump(mode="json")
            draft = _merge_revision(draft, patch, pending, inputs)
            report = validate_eligibility_report(draft, inputs)
        except Exception as exc:
            logger.warning("Critic review or analyst revision failed (%s).", type(exc).__name__)
            entry["error"] = type(exc).__name__
            break
    if pending:
        report = apply_unresolved_findings(report, pending)
    scope = {"invocation_id": inputs.invocation_id, "profile_version": inputs.profile_version}
    context.state[CRITIC_HISTORY_KEY] = history
    context.state[CRITIC_OUTCOME_KEY] = {**scope, "status": status, "revisions": revisions}
    return report


def make_eligibility_callback(analyst, critic):
    """Inject both dynamic nodes so offline workflow tests use controlled models."""

    async def run_eligibility_analysis(
        callback_context: CallbackContext, llm_request: LlmRequest,
    ) -> None:
        state = callback_context.state
        research = state.get(RESEARCH_OUTCOME_KEY) or {}
        if not (
            research.get("status") == "completed"
            and research.get("invocation_id") == callback_context.invocation_id
            and research.get("profile_version") == state.get(PROFILE_VERSION_KEY)
        ):
            return None
        previous = state.get(ELIGIBILITY_OUTCOME_KEY) or {}
        if (
            previous.get("invocation_id") == callback_context.invocation_id
            and previous.get("profile_version") == state.get(PROFILE_VERSION_KEY)
            and previous.get("status") in {"completed", "failed", "not_applicable"}
        ):
            return None

        outcome = {
            "invocation_id": callback_context.invocation_id,
            "profile_version": state.get(PROFILE_VERSION_KEY),
        }
        state[RANKING_KEY] = None
        try:
            inputs = build_analyst_input(callback_context)
            if not inputs.candidates:
                state[RANKING_KEY] = {**outcome, "ranked": [], "held": []}
                state[ELIGIBILITY_REPORT_KEY] = None
                state[ELIGIBILITY_OUTCOME_KEY] = {**outcome, "status": "not_applicable"}
                state[CRITIC_HISTORY_KEY] = []
                state[CRITIC_OUTCOME_KEY] = {**outcome, "status": "not_applicable", "revisions": 0}
                return None
            # Use ADK's dynamic-node path directly: no manufactured function
            # calls, no transfer back into the coordinator, and no extra root
            # model rewrite. Child events remain visible in the ADK trace.
            draft = await _run_draft(callback_context, analyst, inputs.model_dump(mode="json"))
            report = validate_eligibility_report(draft, inputs)
            report = await _review_assessment(callback_context, analyst, critic, inputs, draft, report)
            # Write accepted results AFTER the child finishes. An uncommitted
            # parent reset must not overwrite the child's raw output.
            if state[CRITIC_OUTCOME_KEY]["status"] in {"approved", "revision_limit"}:
                state[RANKING_KEY] = rank_candidates(inputs, draft, report)
            state[ELIGIBILITY_REPORT_KEY] = report.model_dump(mode="json")
            state[ELIGIBILITY_OUTCOME_KEY] = {**outcome, "status": "completed"}
        except Exception as exc:
            logger.warning("Eligibility analysis could not complete (%s).", type(exc).__name__)
            state[ELIGIBILITY_REPORT_KEY] = None
            state[ELIGIBILITY_OUTCOME_KEY] = {
                **outcome, "status": "failed", "reason": "No validated analyst report was accepted.",
            }
            state[CRITIC_HISTORY_KEY] = []
            state[CRITIC_OUTCOME_KEY] = {**outcome, "status": "not_applicable", "revisions": 0}
        return None

    run_eligibility_analysis.analyst_node = analyst
    run_eligibility_analysis.critic_node = critic
    return run_eligibility_analysis
