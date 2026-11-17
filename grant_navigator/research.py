"""Validate the researcher handoff before the coordinator presents a result."""

from __future__ import annotations

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.genai import types

from .eligibility import RULE_LABELS, EligibilityReport, render_eligibility_report
from .ranking import render_ranking
from .notice_evidence import render_notice_evidence
from .tools.intake import (
    PROFILE_KEY, PROFILE_VERSION_KEY, RANKING_KEY,
    CRITIC_HISTORY_KEY, CRITIC_OUTCOME_KEY, ELIGIBILITY_OUTCOME_KEY, ELIGIBILITY_REPORT_KEY, clear_assessment,
    RESEARCH_OUTCOME_KEY, RESEARCH_SUMMARY_KEY,
)


RESEARCH_FAILURE_MESSAGE = (
    "I could not complete grant research in this run. Your nonprofit profile "
    "is saved, but the research step did not return usable findings. This run "
    "does not establish whether matching grants are available. Please try the "
    "search again."
)
BLOCKED_INTAKE_STATUSES = {"needs_profile", "profile_not_prepared"}
AGENT_ERROR_PREFIXES = (
    "error running sub-agent:", "error validating input:",
)


def begin_research(tool, args: dict, tool_context: ToolContext) -> None:
    """Start fresh only after the preceding intake gate permits delegation."""
    if tool.name != "opportunity_researcher":
        return None
    tool_context.state[RESEARCH_SUMMARY_KEY] = None
    clear_assessment(tool_context.state)
    tool_context.state[RESEARCH_OUTCOME_KEY] = {
        "status": "running",
        "invocation_id": tool_context.invocation_id,
        "profile_version": tool_context.state.get(PROFILE_VERSION_KEY),
    }
    return None


def _usable_summary(response: Any) -> str | None:
    # ADK callbacks receive the raw return value, before its function-response
    # wrapper. Accept that wrapper too for explicit checking and saved fixtures.
    if isinstance(response, dict):
        if response.get("error") or response.get("error_code") or response.get("errorCode"):
            return None
        status = response.get("status")
        if isinstance(status, str) and status in {"error", "failed", "research_failed"}:
            return None
        response = response.get("result")
    if not isinstance(response, str):
        return None
    summary = response.strip()
    if (
        not summary
        or summary.casefold() in {"none", "null"}
        or summary.casefold().startswith(AGENT_ERROR_PREFIXES)
    ):
        return None
    return summary


def check_research_result(
    tool, args: dict, tool_context: ToolContext, tool_response: Any,
) -> dict | None:
    """Convert absent/failed child output into an explicit failure, never no matches.

    This verifies that findings were delivered, not that the claims or matches
    are correct. Source and domain validation belong to later project stages.
    """
    if tool.name != "opportunity_researcher":
        return None
    if (
        isinstance(tool_response, dict)
        and isinstance(tool_response.get("status"), str)
        and tool_response["status"] in BLOCKED_INTAKE_STATUSES
    ):
        return None

    summary = _usable_summary(tool_response)
    outcome = {
        "status": "completed" if summary is not None else "failed",
        "invocation_id": tool_context.invocation_id,
        "profile_version": tool_context.state.get(PROFILE_VERSION_KEY),
    }
    tool_context.state[RESEARCH_OUTCOME_KEY] = outcome
    tool_context.state[RESEARCH_SUMMARY_KEY] = summary
    if summary is None:
        return {
            "status": "research_failed",
            "message": RESEARCH_FAILURE_MESSAGE,
        }
    return None


def report_research_failure(
    callback_context: CallbackContext, llm_request: LlmRequest,
) -> LlmResponse | None:
    """Give a fixed failure explanation without another model interpretation."""
    outcome = callback_context.state.get(RESEARCH_OUTCOME_KEY) or {}
    if (
        outcome.get("status") == "failed"
        and outcome.get("invocation_id") == callback_context.invocation_id
    ):
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=RESEARCH_FAILURE_MESSAGE)]),
            finish_reason=types.FinishReason.STOP,
        )
    return None


def _revision_limit_detail(outcome, history):
    count = outcome["revisions"]
    detail = f"The review stopped after {count} {'revision' if count == 1 else 'revisions'}."
    last = history[-1] if history else {}
    assessment = last.get("assessment") or {}
    if not all(assessment.get(key) == outcome[key] for key in ("invocation_id", "profile_version")):
        return detail + " Disputed checks still need verification."

    if (last.get("critic_draft") or {}).get("verdict") == "approve":
        detail += " The AI critic recommended approval of the final draft."
    findings = (last.get("review") or {}).get("findings", [])
    lines = [detail, ""]
    for finding in findings:
        label = RULE_LABELS[finding["rule_id"]]
        if finding["origin"] == "critic":
            reason = "a critic objection remains unresolved"
        elif finding["kind"] == "coverage":
            reason = "the automated check found an incomplete or duplicate assessment"
        else:
            reason = "the automated evidence check found insufficient support"
        lines.append(f"- **{label}** (opportunity {finding['opportunity_id']}) needs verification because {reason}.")
    return "\n".join(lines).strip()


def report_research_completion(
    callback_context: CallbackContext, llm_request: LlmRequest,
) -> LlmResponse | None:
    """Deliver the researcher's text intact instead of asking a model to rewrite it.

    A second generative summary can omit findings or weaken deadline caveats.
    The coordinator adds only a profile summary from the saved user facts.
    """
    state = callback_context.state
    outcome = state.get(RESEARCH_OUTCOME_KEY) or {}
    if not (
        outcome.get("status") == "completed"
        and outcome.get("invocation_id") == callback_context.invocation_id
        and outcome.get("profile_version") == state.get(PROFILE_VERSION_KEY)
    ):
        return None
    summary = state.get(RESEARCH_SUMMARY_KEY)
    if not isinstance(summary, str) or not summary.strip():
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=RESEARCH_FAILURE_MESSAGE)]),
            finish_reason=types.FinishReason.STOP,
        )

    profile = state.get(PROFILE_KEY, {})
    fields = [
        ("Organization type", "organization_type"),
        ("Organization location", "organization_location"),
        ("Project purpose", "project_purpose"),
        ("Service area", "service_area"),
        ("Beneficiaries", "beneficiaries"),
        ("Requested funding", "funding_amount_usd"),
        ("Project timing", "project_timing"),
    ]
    lines = ["**Nonprofit profile**", ""]
    for label, key in fields:
        value = profile.get(key)
        if value is None:
            display = "Unknown"
        elif key == "funding_amount_usd":
            display = f"${value:,.2f} USD"
        else:
            display = str(value).replace("\n", " ")
        lines.append(f"- **{label}:** {display}")
    eligibility_labels = {
        "sam_registration_active": "SAM registration active",
        "has_valid_uei": "Valid UEI held",
        "planned_submission_route": "Planned submission route",
        "americorps_grant_type": "Selected AmeriCorps grant type",
        "americorps_new_applicant": "New AmeriCorps applicant (stated)",
        "can_meet_match": "Can meet applicable match (stated)",
    }
    for key, label in eligibility_labels.items():
        value = profile.get(key)
        if value is not None:
            display = ("Yes" if value else "No") if isinstance(value, bool) else str(value).replace("_", " ")
            lines.append(f"- **{label}:** {display}")
    evidence = render_notice_evidence(state)
    if evidence:
        lines += ["", "---", "", evidence]
    analysis_outcome = state.get(ELIGIBILITY_OUTCOME_KEY) or {}
    current_analysis = (
        analysis_outcome.get("invocation_id") == callback_context.invocation_id
        and analysis_outcome.get("profile_version") == state.get(PROFILE_VERSION_KEY)
    )
    if current_analysis and analysis_outcome.get("status") == "completed":
        accepted = EligibilityReport.model_validate(state[ELIGIBILITY_REPORT_KEY])
        review = state.get(CRITIC_OUTCOME_KEY) or {}
        status = review.get("status") if (
            review.get("invocation_id") == callback_context.invocation_id
            and review.get("profile_version") == state.get(PROFILE_VERSION_KEY)
        ) else None
        if status == "approved":
            count = review["revisions"]
            detail = ("The critic accepted the eligibility checks on the first review." if count == 0 else
                      f"The critic accepted the eligibility checks after {count} {'revision' if count == 1 else 'revisions'}.")
        elif status == "revision_limit":
            detail = _revision_limit_detail(review, state.get(CRITIC_HISTORY_KEY))
        else:
            detail = "The critic review could not finish. Treat these eligibility checks as provisional."
        shortlist = state.get(RANKING_KEY) or {}
        if (status in {"approved", "revision_limit"}
                and shortlist.get("invocation_id") == callback_context.invocation_id
                and shortlist.get("profile_version") == state.get(PROFILE_VERSION_KEY)):
            lines += ["", render_ranking(shortlist)]
        lines += ["", "**Critic review of eligibility checks**", "", detail]
        lines += ["", "---", "", render_eligibility_report(accepted)]
        lines += ["", "**Researcher’s discovery notes (outside the critic review)**"]
    elif current_analysis and analysis_outcome.get("status") == "not_applicable":
        lines += ["", "**Grants to investigate first**", "",
                  "This search retrieved no grant details to rank. Try a broader term for the "
                  "project activity or provide a Grants.gov opportunity ID to investigate."]
    elif current_analysis and analysis_outcome.get("status") == "failed":
        lines += [
            "", "---", "", "**Eligibility review incomplete**", "",
            "The analyst did not return a validated review. The research findings "
            "below remain unverified; this run does not establish eligibility.",
        ]
    text = "\n".join(lines) + "\n\n---\n\n" + summary
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        finish_reason=types.FinishReason.STOP,
    )
