"""Session-scoped profile updates and enforced intake-to-research handoff."""

from __future__ import annotations

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import ValidationError

from ..profile import NonprofitProfile


PROFILE_KEY = "nonprofit_profile"
PROFILE_VERSION_KEY = "profile_version"
PREPARED_INVOCATION_KEY = "temp:profile_prepared_invocation"
ALLOWED_VERSION_KEY = "temp:research_allowed_profile_version"
VALIDATION_ERRORS_KEY = "intake_validation_errors"
INVALID_FIELDS_KEY = "intake_invalid_fields"
MIXED_BATCH_KEY = "temp:mixed_intake_research_batch"
RESEARCH_SUMMARY_KEY = "research_summary"
RESEARCH_OUTCOME_KEY = "research_outcome"
RESEARCH_EVIDENCE_KEY = "research_evidence"
ELIGIBILITY_REPORT_KEY = "eligibility_analysis"
ELIGIBILITY_OUTCOME_KEY = "eligibility_outcome"
RANKING_KEY = "grant_shortlist"
CRITIC_HISTORY_KEY = "critic_history"
CRITIC_OUTCOME_KEY = "critic_outcome"


def clear_assessment(state) -> None:
    state[RANKING_KEY] = None
    state[ELIGIBILITY_REPORT_KEY] = None
    state[ELIGIBILITY_OUTCOME_KEY] = None
    state[CRITIC_HISTORY_KEY] = []
    state[CRITIC_OUTCOME_KEY] = None


def profile_status(state) -> dict:
    """Revalidate stored data rather than trusting a model-written ready flag."""
    try:
        profile = NonprofitProfile.model_validate(state.get(PROFILE_KEY, {}))
    except ValidationError:
        return {
            "ready_for_research": False,
            "missing_required_fields": [],
            "follow_up_questions": ["Please correct the saved nonprofit profile before searching."],
            "unknown_matching_fields": [],
            "validation_errors": ["Saved profile is invalid."],
        }
    status = profile.discovery_status()
    if errors := state.get(VALIDATION_ERRORS_KEY):
        status["ready_for_research"] = False
        status["validation_errors"] = errors
    return status


def save_nonprofit_profile(
    tool_context: ToolContext,
    organization_name: str | None = None,
    organization_type: str | None = None,
    organization_location: str | None = None,
    project_purpose: str | None = None,
    service_area: str | None = None,
    beneficiaries: str | None = None,
    funding_amount_usd: float | None = None,
    project_timing: str | None = None,
    sam_registration_active: bool | None = None,
    has_valid_uei: bool | None = None,
    planned_submission_route: str | None = None,
    americorps_grant_type: str | None = None,
    americorps_new_applicant: bool | None = None,
    can_meet_match: bool | None = None,
    clear_fields: list[str] | None = None,
) -> dict:
    """Save facts the user supplied, or validate the current profile before research.

    Only supplied non-null fields replace saved values. Omitted/null fields
    keep previous values; use clear_fields to remove a previous fact. Never
    infer project geography from headquarters or invent missing details.

    Args:
        organization_name: Organization's name, if provided.
        organization_type: Applicant type in the user's own terms.
        organization_location: Organization's location or headquarters.
        project_purpose: Activities or outcomes the proposed grant would fund.
        service_area: Where the project operates, only if the user specifies it.
        beneficiaries: People or communities served by the project.
        funding_amount_usd: Requested funding in USD; omit when unknown.
        project_timing: User's stated project schedule or application timeline.
        sam_registration_active: Whether the user reports active SAM registration.
        has_valid_uei: Whether the user reports having a valid UEI; never collect the identifier itself.
        planned_submission_route: User's chosen route: state_commission or direct; omit if undecided.
        americorps_grant_type: Stated AmeriCorps mechanism: cost_reimbursement, full_cost_fixed_amount, education_award_program, professional_corps, or fixed_amount_unspecified.
        americorps_new_applicant: Whether the user explicitly reports being new under the AmeriCorps applicant definition.
        can_meet_match: Whether the user reports being able to meet the applicable matching requirement.
        clear_fields: Names of saved fields to reset to unknown.

    Returns:
        Validated profile, discovery readiness, questions, and remaining unknowns.
    """
    state = tool_context.state
    updates = {
        key: value for key, value in {
            "organization_name": organization_name,
            "organization_type": organization_type,
            "organization_location": organization_location,
            "project_purpose": project_purpose,
            "service_area": service_area,
            "beneficiaries": beneficiaries,
            "funding_amount_usd": funding_amount_usd,
            "project_timing": project_timing,
            "sam_registration_active": sam_registration_active,
            "has_valid_uei": has_valid_uei,
            "planned_submission_route": planned_submission_route,
            "americorps_grant_type": americorps_grant_type,
            "americorps_new_applicant": americorps_new_applicant,
            "can_meet_match": can_meet_match,
        }.items() if value is not None
    }
    errors = []
    invalid_fields = set()
    if clear_fields is not None:
        if not isinstance(clear_fields, list) or any(
            not isinstance(field, str) or field not in NonprofitProfile.model_fields
            for field in clear_fields
        ):
            errors.append("clear_fields must be a list of valid profile field names.")
            invalid_fields.add("clear_fields")
        elif set(clear_fields) & updates.keys():
            errors.append("A field cannot be updated and cleared in the same call.")
            invalid_fields.update(set(clear_fields) & updates.keys())
        else:
            updates.update({field: None for field in clear_fields})
    try:
        previous = state.get(PROFILE_KEY, {})
        profile = NonprofitProfile.model_validate({**previous, **updates})
    except (ValidationError, TypeError) as exc:
        if isinstance(exc, ValidationError):
            errors.extend(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in exc.errors(include_input=False, include_url=False)
            )
            invalid_fields.update(str(item["loc"][0]) for item in exc.errors() if item["loc"])
        else:
            errors.append("Saved profile must be an object; start a new session.")
            invalid_fields.add("saved_profile")
    resolved_fields = set(updates)
    if clear_fields is not None and "clear_fields" not in invalid_fields:
        resolved_fields.add("clear_fields")
    outstanding = set(state.get(INVALID_FIELDS_KEY, [])) - resolved_fields
    if outstanding:
        errors.append("Correct or explicitly clear these fields before research: " + ", ".join(sorted(outstanding)))
        invalid_fields.update(outstanding)
    if errors:
        # Preserve prior valid facts but block research until this update is corrected.
        state[VALIDATION_ERRORS_KEY] = errors
        state[INVALID_FIELDS_KEY] = sorted(invalid_fields)
        state[PREPARED_INVOCATION_KEY] = None
        state[ALLOWED_VERSION_KEY] = None
        state[RESEARCH_SUMMARY_KEY] = None
        state[RESEARCH_OUTCOME_KEY] = None
        state[RESEARCH_EVIDENCE_KEY] = None
        clear_assessment(state)
        return {"status": "invalid_profile", "ready_for_research": False, "validation_errors": errors}

    saved = profile.model_dump(mode="json")
    if saved != previous:
        state[PROFILE_VERSION_KEY] = state.get(PROFILE_VERSION_KEY, 0) + 1
        state[RESEARCH_SUMMARY_KEY] = None
        state[RESEARCH_OUTCOME_KEY] = None
        state[RESEARCH_EVIDENCE_KEY] = None
        clear_assessment(state)
        # A parallel delegation must not use permission issued for an older profile.
        state[ALLOWED_VERSION_KEY] = None
    state[PROFILE_KEY] = saved
    state[VALIDATION_ERRORS_KEY] = []
    state[INVALID_FIELDS_KEY] = []
    state[PREPARED_INVOCATION_KEY] = tool_context.invocation_id
    return {
        "status": "saved",
        "profile": saved,
        "profile_version": state[PROFILE_VERSION_KEY],
        **profile.discovery_status(),
    }


def prepare_research_handoff(callback_context: CallbackContext, llm_request: LlmRequest):
    """Permit delegation only in a model turn AFTER a validated profile save.

    ADK can execute a batch of tool calls concurrently. A save and delegation
    in the same batch must not race or accidentally research an older profile.
    """
    state = callback_context.state
    state[MIXED_BATCH_KEY] = False
    prepared = state.get(PREPARED_INVOCATION_KEY) == callback_context.invocation_id
    state[ALLOWED_VERSION_KEY] = (
        state.get(PROFILE_VERSION_KEY)
        if prepared and profile_status(state)["ready_for_research"] else None
    )
    return None


def block_mixed_profile_research_batch(callback_context: CallbackContext, llm_response: LlmResponse):
    """Mark mixed batches before tools start so research can be blocked."""
    parts = llm_response.content.parts if llm_response.content else []
    calls = {part.function_call.name for part in parts or [] if part.function_call}
    callback_context.state[MIXED_BATCH_KEY] = {
        "save_nonprofit_profile", "opportunity_researcher"
    }.issubset(calls)
    return None


def research_gate(context) -> dict | None:
    state = context.state
    if state.get(MIXED_BATCH_KEY):
        return {
            "status": "profile_not_prepared",
            "ready_for_research": False,
            "message": "Save and research must be separate steps. Wait for the save result, then delegate research.",
        }
    status = profile_status(state)
    if not status["ready_for_research"]:
        return {"status": "needs_profile", **status}
    version = state.get(PROFILE_VERSION_KEY)
    if (
        state.get(PREPARED_INVOCATION_KEY) != context.invocation_id
        or version is None
        or state.get(ALLOWED_VERSION_KEY) != version
    ):
        return {
            "status": "profile_not_prepared",
            "ready_for_research": False,
            "message": "Save or validate the current profile, wait for its result, then delegate research.",
        }
    return None


def gate_research_delegation(tool, args: dict, tool_context: ToolContext) -> dict | None:
    if tool.name == "opportunity_researcher":
        return research_gate(tool_context)
    return None


def gate_research_agent(callback_context: CallbackContext) -> types.Content | None:
    """Also protect the child agent if it is invoked without the coordinator."""
    if blocked := research_gate(callback_context):
        questions = blocked.get("follow_up_questions") or blocked.get("validation_errors") or [blocked.get("message", "Please correct the profile first.")]
        return types.Content(role="model", parts=[types.Part(text="Before grant research: " + " ".join(questions))])
    return None


def gate_research_tools(tool, args: dict, tool_context: ToolContext) -> dict | None:
    return research_gate(tool_context)
