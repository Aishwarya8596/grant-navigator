"""Keep document evidence tied to the opportunity and current research attempt."""

from __future__ import annotations

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.genai import types

from .opportunities import normalize_opportunity
from .tools.intake import PROFILE_VERSION_KEY, RESEARCH_EVIDENCE_KEY, RESEARCH_OUTCOME_KEY


MIXED_NOTICE_BATCH_KEY = "temp:mixed_detail_notice_batch"
NOTICE_REQUEST_ROUNDS_KEY = "temp:notice_request_rounds"
MAX_NOTICE_REQUEST_ROUNDS = 6
INTAKE_BLOCKS = {"needs_profile", "profile_not_prepared", "notice_not_ready"}


def begin_notice_research(callback_context: CallbackContext) -> None:
    """The researcher owns its evidence reset, before it starts tool calls.

    Do not initialize this key in the parent's before-tool callback: its still
    pending state delta could overwrite the nested researcher's later updates.
    """
    callback_context.state[RESEARCH_EVIDENCE_KEY] = {
        "invocation_id": callback_context.invocation_id,
        "profile_version": callback_context.state.get(PROFILE_VERSION_KEY),
        "details": {}, "notices": {}, "search_hits": {},
    }
    callback_context.state[MIXED_NOTICE_BATCH_KEY] = False
    callback_context.state[NOTICE_REQUEST_ROUNDS_KEY] = 0
    return None


def _opportunity_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if number > 0 and str(number) == str(value) else None


def _current_evidence(context) -> dict:
    evidence = context.state.get(RESEARCH_EVIDENCE_KEY) or {}
    if (
        evidence.get("invocation_id") != context.invocation_id
        or evidence.get("profile_version") != context.state.get(PROFILE_VERSION_KEY)
    ):
        return {
            "invocation_id": context.invocation_id,
            "profile_version": context.state.get(PROFILE_VERSION_KEY),
            "details": {},
            "notices": {},
            "search_hits": {},
        }
    return evidence


def gate_notice_read(tool, args: dict, tool_context: ToolContext) -> dict | None:
    if tool.name != "read_grant_notice":
        return None
    opportunity_id = _opportunity_id(args.get("opportunity_id"))
    evidence = _current_evidence(tool_context)
    if (
        opportunity_id is None
        or str(opportunity_id) not in evidence["details"]
        or tool_context.state.get(MIXED_NOTICE_BATCH_KEY)
    ):
        return {
            "status": "notice_not_ready",
            "message": "Fetch this opportunity's details in a separate step before reading its notice.",
            "opportunity_id": opportunity_id,
        }
    return None


def record_research_evidence(
    tool, args: dict, tool_context: ToolContext, tool_response: Any,
) -> dict | None:
    """Record actual tool results; a synopsis never becomes notice evidence."""
    if not isinstance(tool_response, dict):
        return None
    if tool.name == "search_grants" and tool_response.get("status") == "success":
        evidence = dict(_current_evidence(tool_context))
        hits = dict(evidence.get("search_hits", {}))
        for hit in tool_response.get("opportunities", []):
            if isinstance(hit, dict) and (found_id := _opportunity_id(hit.get("id"))):
                hits[str(found_id)] = dict(hit)
        evidence["search_hits"] = hits
        tool_context.state[RESEARCH_EVIDENCE_KEY] = evidence
        return None
    opportunity_id = _opportunity_id(args.get("opportunity_id"))
    if opportunity_id is None:
        return None
    evidence = dict(_current_evidence(tool_context))
    if tool.name == "fetch_grant_details" and tool_response.get("status") == "success":
        if _opportunity_id(tool_response.get("id")) != opportunity_id:
            return {
                "status": "detail_mismatch",
                "message": "The returned opportunity ID does not match the requested ID; details were not accepted.",
            }
        details = dict(evidence["details"])
        try:
            opportunity = normalize_opportunity(
                tool_response, evidence.get("search_hits", {}).get(str(opportunity_id)),
            )
        except ValueError:
            return {
                "status": "detail_mismatch",
                "message": "Opportunity facts could not be normalized consistently; they were not accepted for analysis.",
            }
        details[str(opportunity_id)] = {
            "id": opportunity_id,
            "number": tool_response.get("number"),
            "title": tool_response.get("title"),
            "opportunity": opportunity.model_dump(mode="json"),
        }
        evidence["details"] = details
        tool_context.state[RESEARCH_EVIDENCE_KEY] = evidence
        # Keep the API timestamp in the evidence record. The discovery model
        # only needs the calendar date; the notice supplies the cutoff time.
        date = opportunity.api_general_deadline_date
        return {**tool_response, "agency": opportunity.agency,
                "response_date": date.isoformat() if date else None}
    elif tool.name == "read_grant_notice":
        status = tool_response.get("status")
        if isinstance(status, str) and status in INTAKE_BLOCKS:
            return None
        detail = evidence["details"].get(str(opportunity_id))
        if detail is None:
            return {"status": "notice_not_ready", "message": "No current opportunity detail supports this notice."}
        accepted = tool_response
        if (
            _opportunity_id(tool_response.get("opportunity_id")) != opportunity_id
            or (
                status == "success"
                and tool_response.get("opportunity_number") != detail.get("number")
            )
        ):
            accepted = {
                "status": "notice_mismatch",
                "opportunity_id": opportunity_id,
                "excerpts": [],
                "message": "Notice identity does not match the fetched opportunity; its excerpts were not accepted.",
                "eligibility_status": "not_assessed",
            }
        notices = dict(evidence["notices"])
        previous = notices.get(str(opportunity_id), {})
        stored = dict(accepted)
        attempts = list(previous.get("read_attempts", []))
        attempts.append({"focus": args.get("focus", "default"), "status": accepted.get("status")})
        if (
            previous.get("status") == "success"
            and accepted.get("status") == "success"
            and previous.get("source_sha256") == accepted.get("source_sha256")
        ):
            # Keep passages from earlier focused reads. The model may ask
            # separately about deadlines and cost sharing in the same task.
            excerpts = {
                item["evidence_id"]: item
                for item in [*previous.get("excerpts", []), *accepted.get("excerpts", [])]
            }
            stored["excerpts"] = list(excerpts.values())
        elif (
            previous.get("status") == "success"
            and accepted.get("status") == "no_matching_excerpts"
            and previous.get("source_sha256") == accepted.get("source_sha256")
        ):
            stored = dict(previous)
            stored["last_read_status"] = "no_matching_excerpts"
        stored["read_attempts"] = attempts
        notices[str(opportunity_id)] = stored
        evidence["notices"] = notices
        tool_context.state[RESEARCH_EVIDENCE_KEY] = evidence
        if accepted is not tool_response:
            return accepted
    return None


def require_notice_request(
    callback_context: CallbackContext, llm_request: LlmRequest,
) -> LlmResponse | None:
    """Ask the provider to generate a genuine notice call while reads are pending.

    Gemini signs its function-call parts. Constructing a call in an after-model
    callback loses that provider signature, so enforce the next action using
    the native function-calling configuration instead of editing model history.
    """
    evidence = _current_evidence(callback_context)
    pending = [key for key in evidence["details"] if key not in evidence["notices"]]
    config = llm_request.config.tool_config or types.ToolConfig()
    if pending:
        rounds = callback_context.state.get(NOTICE_REQUEST_ROUNDS_KEY, 0)
        if rounds >= MAX_NOTICE_REQUEST_ROUNDS:
            return LlmResponse(
                error_code="NOTICE_REVIEW_INCOMPLETE",
                error_message="The required notice-read step exceeded its model-turn limit.",
            )
        callback_context.state[NOTICE_REQUEST_ROUNDS_KEY] = rounds + 1
        llm_request.config.tool_config = config.model_copy(update={
            "function_calling_config": types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=["read_grant_notice"],
            ),
        })
        llm_request.append_instructions([
            "Before answering, call read_grant_notice for these fetched opportunity IDs: "
            + ", ".join(pending)
            + ". Use separate calls for multiple IDs. For a combined deadline, "
              "application-route, and cost-sharing question, request at least six excerpts. "
              "After the tool results, explain their evidence and unresolved limitations."
        ])
    elif (
        config.function_calling_config
        and config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
        and config.function_calling_config.allowed_function_names == ["read_grant_notice"]
    ):
        llm_request.config.tool_config = config.model_copy(update={
            "function_calling_config": types.FunctionCallingConfig(mode="AUTO"),
        })
    return None


def ensure_notice_attempts(
    callback_context: CallbackContext, llm_response: LlmResponse,
) -> LlmResponse | None:
    """Keep provider-signed calls intact; reject a final answer that skips reads."""
    parts = llm_response.content.parts if llm_response.content else []
    calls = [part.function_call for part in parts or [] if part.function_call]
    names = {call.name for call in calls}
    callback_context.state[MIXED_NOTICE_BATCH_KEY] = {
        "fetch_grant_details", "read_grant_notice"
    }.issubset(names)
    if (
        llm_response.partial
        or llm_response.interrupted
        or llm_response.error_code
        or llm_response.finish_reason not in (None, types.FinishReason.STOP)
    ):
        return None
    evidence = _current_evidence(callback_context)
    pending = [key for key in evidence["details"] if key not in evidence["notices"]]
    if not pending:
        return None
    if calls:
        if "read_grant_notice" in names:
            metadata = dict(llm_response.custom_metadata or {})
            metadata["notice_read_enforced"] = [int(key) for key in pending]
            # Preserve the original content and thought_signature bytes.
            return llm_response.model_copy(update={"custom_metadata": metadata})
        return None
    if not any(part.text and part.text.strip() and not part.thought for part in parts or []):
        return None
    return llm_response.model_copy(update={
        "content": None,
        "error_code": "NOTICE_REVIEW_INCOMPLETE",
        "error_message": "Research ended before the required notice attempts completed.",
    })


def render_notice_evidence(state) -> str:
    """Describe source access without claiming complete or current eligibility review."""
    evidence = state.get(RESEARCH_EVIDENCE_KEY) or {}
    outcome = state.get(RESEARCH_OUTCOME_KEY) or {}
    if (
        evidence.get("invocation_id") != outcome.get("invocation_id")
        or evidence.get("profile_version") != state.get(PROFILE_VERSION_KEY)
    ):
        return ""
    details = evidence.get("details", {})
    if not details:
        return ""
    lines = ["**Notice sources retrieved**", ""]
    for key, detail in details.items():
        result = evidence.get("notices", {}).get(key, {})
        label = detail.get("number") or key
        status = result.get("status", "not_reviewed")
        if status == "success":
            pages = sorted({item["page_number"] for item in result.get("excerpts", [])})
            source = result["source_url"].split("#", 1)[0]
            links = ", ".join(f"[p. {page}]({source}#page={page})" for page in pages)
            date = (result.get("snapshot_captured_at_utc") or "unknown")[:10]
            mode = result.get("retrieval_mode", "snapshot")
            mode_label = "saved snapshot" if mode == "saved_snapshot" else "verified snapshot downloaded"
            lines.append(f"- **{label}:** Notice excerpts retrieved ({links}); {mode_label}, captured {date}.")
        elif status == "no_matching_excerpts":
            lines.append(f"- **{label}:** The notice was readable, but the query returned no excerpts. Rules remain unverified.")
        else:
            lines.append(f"- **{label}:** Full-notice evidence unavailable ({status.replace('_', ' ')}); synopsis-only discovery.")
    lines += ["", "These are selected excerpts. Current amendments, applicant-specific deadlines, and eligibility remain unverified."]
    return "\n".join(lines)
