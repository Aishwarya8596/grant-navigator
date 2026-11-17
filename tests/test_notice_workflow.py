"""Verify page evidence is actually read and scoped to the current ADK run.

These use the real ADK callbacks and the saved notice. Model choices and the
Grants.gov HTTP boundary are controlled; they do not evaluate grant fit.
"""

from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
import pytest

from grant_navigator import notice_evidence
from grant_navigator.research import RESEARCH_FAILURE_MESSAGE, begin_research
from grant_navigator.tools import grants_gov, intake, notices
from test_intake_workflow import (
    coordinator,
    coordinator_text,
    run_session,
    text_turn,
    tool_responses,
    tool_turn,
)


KNOWN_ID = 363696
KNOWN_NUMBER = "AC-08-28-26"
SOURCE_URL = (
    "https://www.oregon.gov/oregonserves/americorps/Documents/"
    "2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf"
)
FOCUS = "single-state state commission application deadline"


@pytest.fixture
def install_grants(monkeypatch):
    def install(opportunity_id=KNOWN_ID, number=KNOWN_NUMBER):
        calls = []

        def fake_post(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "search2":
                return {
                    "hitCount": 1,
                    "oppHits": [{
                        "id": str(opportunity_id), "number": number,
                        "title": "Controlled grant candidate", "oppStatus": "posted",
                    }],
                }
            assert endpoint == "fetchOpportunity"
            assert payload["opportunityId"] == opportunity_id
            return {
                "id": opportunity_id,
                "opportunityNumber": number,
                "opportunityTitle": "Controlled grant candidate",
                "synopsis": {"synopsisDesc": "A synthetic synopsis for orchestration checks."},
            }

        monkeypatch.setattr(grants_gov, "_post_json", fake_post)
        return calls

    return install


def root_turns(profile=None):
    return [
        tool_turn(("save_nonprofit_profile", profile if profile is not None else {
            "organization_type": "501(c)(3) nonprofit",
            "organization_location": "California",
            "project_purpose": "community volunteer programs",
        })),
        tool_turn(("opportunity_researcher", {"request": "Research grants and read the notice."})),
    ]


def evidence_context(details=True, invocation_id="current-invocation"):
    state = {
        intake.PROFILE_VERSION_KEY: 1,
        intake.RESEARCH_EVIDENCE_KEY: {
            "invocation_id": invocation_id,
            "profile_version": 1,
            "details": {str(KNOWN_ID): {
                "id": KNOWN_ID, "number": KNOWN_NUMBER, "title": "Controlled grant candidate",
            }} if details else {},
            "notices": {},
        },
    }
    return SimpleNamespace(state=state, invocation_id=invocation_id)


def test_notice_pages_and_snapshot_reach_final_answer_through_actual_adk(install_grants):
    calls = install_grants()
    findings = (
        "The single-state application route needs review; service area is unknown.\n"
        f"Evidence: [Full notice, PDF page 8]({SOURCE_URL}#page=8).\n"
        "Eligibility has not been assessed."
    )
    agent, root_model, research_model, _ = coordinator(root_turns(), [
        tool_turn(("search_grants", {"keyword": "community volunteer programs", "rows": 3})),
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        tool_turn(("read_grant_notice", {"opportunity_id": KNOWN_ID, "focus": FOCUS})),
        text_turn(findings),
    ])

    turns, session = run_session(agent, ["Find grants for our California nonprofit volunteer project."])

    result = tool_responses(turns[0], "read_grant_notice")[-1]
    assert result["status"] == "success"
    assert result["page_count"] == 28
    assert result["eligibility_status"] == "not_assessed"
    assert result["currentness_verified"] is False
    assert 8 in {excerpt["page_number"] for excerpt in result["excerpts"]}
    # A successful child tool response alone is insufficient: the parent's
    # pending state delta must not overwrite the evidence when handoff ends.
    evidence = session.state[intake.RESEARCH_EVIDENCE_KEY]
    assert evidence["profile_version"] == session.state[intake.PROFILE_VERSION_KEY]
    assert evidence["details"][str(KNOWN_ID)]["number"] == KNOWN_NUMBER
    assert evidence["notices"][str(KNOWN_ID)]["source_sha256"] == result["source_sha256"]
    answer = coordinator_text(turns[0])
    assert answer.endswith(findings)
    assert SOURCE_URL in answer and "#page=8" in answer
    assert "2026-11-10" in answer  # Snapshot caveat cannot disappear in a model rewrite.
    assert session.state[intake.PROFILE_KEY]["service_area"] is None
    assert [endpoint for endpoint, _ in calls] == ["search2", "fetchOpportunity"]
    assert len(root_model.requests) == 2 and len(research_model.requests) == 4
    assert not root_model.responses and not research_model.responses


def test_pending_notice_read_uses_native_tool_config_and_preserves_signed_call(install_grants):
    install_grants()
    findings = "Findings after actually reading notice excerpts; eligibility remains unverified."
    # This is a synthetic opaque signature, not provider credentials. The
    # callback may tag metadata, but must preserve the provider-owned Part.
    signature = b"opaque-test-signature"
    signed_part = types.Part(
        function_call=types.FunctionCall(
            id="signed-notice-call", name="read_grant_notice",
            args={"opportunity_id": KNOWN_ID, "focus": FOCUS},
        ),
        thought_signature=signature,
    )
    provider_response = LlmResponse(
        content=types.Content(role="model", parts=[signed_part]),
        finish_reason=types.FinishReason.STOP,
    )
    tagged = notice_evidence.ensure_notice_attempts(evidence_context(), provider_response)
    assert tagged.content is provider_response.content
    assert tagged.content.parts[0] is provider_response.content.parts[0]
    assert tagged.content.parts[0].thought_signature == signature
    assert tagged.content.parts[0].function_call.id == "signed-notice-call"

    agent, _, research_model, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        provider_response,
        text_turn(findings),
    ])

    turns, session = run_session(agent, ["Inspect the grant notice for our nonprofit project."])

    notice_events = [
        event for event in turns[0]
        if any(call.name == "read_grant_notice" for call in event.get_function_calls())
    ]
    assert len(notice_events) == 1
    assert notice_events[0].custom_metadata.get("notice_read_enforced")
    delivered_part = next(
        part for part in notice_events[0].content.parts
        if part.function_call and part.function_call.name == "read_grant_notice"
    )
    assert delivered_part.thought_signature == signature
    assert delivered_part.function_call.id == "signed-notice-call"
    assert delivered_part.function_call.args == signed_part.function_call.args
    # The model generated the call in response to its native function-calling
    # configuration; no callback constructed an unsigned call afterward.
    native_config = research_model.requests[1].config.tool_config.function_calling_config
    assert native_config.mode == types.FunctionCallingConfigMode.ANY
    assert native_config.allowed_function_names == ["read_grant_notice"]
    assert str(KNOWN_ID) in str(research_model.requests[1].config.system_instruction)
    final_config = research_model.requests[-1].config.tool_config
    assert (
        final_config is None
        or final_config.function_calling_config is None
        or final_config.function_calling_config.mode == types.FunctionCallingConfigMode.AUTO
    )
    assert tool_responses(turns[0], "read_grant_notice")[-1]["status"] == "success"
    assert coordinator_text(turns[0]).endswith(findings)
    assert session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)]["excerpts"]
    assert len(research_model.requests) == 3
    assert any(
        part.function_response and part.function_response.name == "read_grant_notice"
        for content in research_model.requests[-1].contents for part in content.parts or []
    )


def test_final_text_that_skips_native_required_notice_read_fails_closed(install_grants):
    calls = install_grants()
    premature = "Premature claim that the full notice has been checked."
    agent, root_model, research_model, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        text_turn(premature),
    ])

    turns, session = run_session(agent, ["Inspect the notice before answering."])

    assert any(event.error_code == "NOTICE_REVIEW_INCOMPLETE" for event in turns[0])
    assert not any(
        call.name == "read_grant_notice"
        for event in turns[0] for call in event.get_function_calls()
    )  # The guard must not manufacture a provider call to repair this reply.
    assert premature not in coordinator_text(turns[0])
    assert coordinator_text(turns[0]) == RESEARCH_FAILURE_MESSAGE
    assert tool_responses(turns[0], "opportunity_researcher")[-1]["status"] == "research_failed"
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "failed"
    assert session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"] == {}
    assert len(root_model.requests) == 2 and len(research_model.requests) == 2
    assert [endpoint for endpoint, _ in calls] == ["fetchOpportunity"]


def test_native_notice_configuration_returns_to_auto_after_attempt_completes():
    context = evidence_context()
    request = LlmRequest(model="offline-test", contents=[])

    assert notice_evidence.require_notice_request(context, request) is None
    forced = request.config.tool_config.function_calling_config
    assert forced.mode == types.FunctionCallingConfigMode.ANY
    assert forced.allowed_function_names == ["read_grant_notice"]
    assert context.state[notice_evidence.NOTICE_REQUEST_ROUNDS_KEY] == 1

    context.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)] = {"status": "notice_unavailable"}
    assert notice_evidence.require_notice_request(context, request) is None
    restored = request.config.tool_config.function_calling_config
    assert restored.mode == types.FunctionCallingConfigMode.AUTO
    assert not restored.allowed_function_names
    assert context.state[notice_evidence.NOTICE_REQUEST_ROUNDS_KEY] == 1


def test_native_notice_request_budget_returns_error_on_the_seventh_pending_turn():
    context = evidence_context()
    for count in range(1, notice_evidence.MAX_NOTICE_REQUEST_ROUNDS + 1):
        request = LlmRequest(model="offline-test", contents=[])
        assert notice_evidence.require_notice_request(context, request) is None
        assert request.config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
        assert context.state[notice_evidence.NOTICE_REQUEST_ROUNDS_KEY] == count

    exhausted = notice_evidence.require_notice_request(context, LlmRequest(model="offline-test", contents=[]))

    assert exhausted.error_code == "NOTICE_REVIEW_INCOMPLETE"
    assert exhausted.content is None and not exhausted.get_function_calls()
    assert context.state[notice_evidence.NOTICE_REQUEST_ROUNDS_KEY] == notice_evidence.MAX_NOTICE_REQUEST_ROUNDS


def test_unproductive_notice_calls_stop_without_an_extra_model_request(install_grants):
    calls = install_grants()
    agent, root_model, research_model, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        *[
            tool_turn(("read_grant_notice", {"opportunity_id": 999999}))
            for _ in range(notice_evidence.MAX_NOTICE_REQUEST_ROUNDS)
        ],
        # No further model response exists: the before-model budget must stop
        # the loop before another provider request is made.
    ])

    turns, session = run_session(agent, ["Read the notice for this fetched candidate."])

    assert any(event.error_code == "NOTICE_REVIEW_INCOMPLETE" for event in turns[0])
    results = tool_responses(turns[0], "read_grant_notice")
    assert len(results) == notice_evidence.MAX_NOTICE_REQUEST_ROUNDS
    assert all(result["status"] == "notice_not_ready" for result in results)
    assert len(research_model.requests) == 1 + notice_evidence.MAX_NOTICE_REQUEST_ROUNDS
    assert len(root_model.requests) == 2
    assert not research_model.responses
    assert session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"] == {}
    assert coordinator_text(turns[0]) == RESEARCH_FAILURE_MESSAGE
    assert [endpoint for endpoint, _ in calls] == ["fetchOpportunity"]


def test_uncataloged_notice_is_a_nonfatal_explicit_evidence_status(install_grants):
    calls = install_grants(9001, "OFFLINE-1")
    findings = "Synopsis-only candidate. Full-notice eligibility verification is still needed."
    agent, _, _, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
        tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
        text_turn(findings),
    ])

    turns, session = run_session(agent, ["Research our nonprofit project."])

    result = tool_responses(turns[0], "read_grant_notice")[-1]
    assert result["status"] == "notice_unavailable"
    assert result["excerpts"] == [] and result["eligibility_status"] == "not_assessed"
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "completed"
    assert session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"]["9001"]["status"] == "notice_unavailable"
    assert "unavailable" in coordinator_text(turns[0]).casefold()
    assert coordinator_text(turns[0]).endswith(findings)
    assert [endpoint for endpoint, _ in calls] == ["fetchOpportunity"]


def test_read_before_details_cannot_expose_pdf_evidence_and_can_recover(install_grants):
    calls = install_grants()
    agent, _, _, _ = coordinator(root_turns(), [
        tool_turn(("read_grant_notice", {"opportunity_id": KNOWN_ID})),
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        tool_turn(("read_grant_notice", {"opportunity_id": KNOWN_ID, "focus": FOCUS})),
        text_turn("Notice excerpts are now available after detail retrieval."),
    ])

    turns, session = run_session(agent, ["Inspect the notice."])

    results = tool_responses(turns[0], "read_grant_notice")
    assert len(results) == 2
    assert results[0]["status"] != "success" and not results[0].get("excerpts")
    assert results[1]["status"] == "success"
    assert session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)]["status"] == "success"
    assert [endpoint for endpoint, _ in calls] == ["fetchOpportunity"]


@pytest.mark.parametrize("read_first", [False, True])
def test_fetch_and_read_batch_cannot_race_into_unbound_notice_evidence(install_grants, read_first):
    calls = install_grants()
    batch = [
        ("fetch_grant_details", {"opportunity_id": KNOWN_ID}),
        ("read_grant_notice", {"opportunity_id": KNOWN_ID}),
    ]
    if read_first:
        batch.reverse()
    agent, _, _, _ = coordinator(root_turns(), [
        tool_turn(*batch),
        tool_turn(("read_grant_notice", {"opportunity_id": KNOWN_ID, "focus": FOCUS})),
        text_turn("The separately retrieved notice has source-linked excerpts."),
    ])

    turns, session = run_session(agent, ["Inspect our grant candidate and notice."])

    results = tool_responses(turns[0], "read_grant_notice")
    assert results[0]["status"] != "success" and not results[0].get("excerpts")
    assert results[1]["status"] == "success"
    assert session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)]["source_url"] == SOURCE_URL
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    {"opportunity_id": KNOWN_ID + 1},
    {"opportunity_number": "WRONG-NOTICE"},
])
def test_notice_binding_mismatch_removes_excerpts_before_the_model_sees_them(change):
    context = evidence_context()
    result = notices.read_grant_notice(KNOWN_ID, focus=FOCUS)
    assert result["status"] == "success"
    result.update(change)

    altered = notice_evidence.record_research_evidence(
        SimpleNamespace(name="read_grant_notice"), {"opportunity_id": KNOWN_ID}, context, result
    )

    assert altered["status"] == "notice_mismatch"
    assert altered["excerpts"] == []
    saved = context.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)]
    assert saved["status"] == "notice_mismatch" and not saved["excerpts"]


def test_no_matching_excerpt_counts_as_an_attempt_not_a_rule_absence(install_grants):
    install_grants()
    findings = "The source was readable, but this query did not locate evidence for that term."
    agent, _, research_model, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        tool_turn(("read_grant_notice", {"opportunity_id": KNOWN_ID, "focus": "zzzzunfindableterm"})),
        text_turn(findings),
    ])

    turns, session = run_session(agent, ["Find the rule in the notice."])

    results = tool_responses(turns[0], "read_grant_notice")
    assert len(results) == 1 and results[0]["status"] == "no_matching_excerpts"
    assert results[0]["page_count"] == 28
    assert results[0]["eligibility_status"] == "not_assessed"
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "completed"
    assert coordinator_text(turns[0]).endswith(findings)
    assert len(research_model.requests) == 3


def test_new_attempt_clears_old_notice_evidence_even_when_profile_is_unchanged(install_grants):
    install_grants(9001, "OFFLINE-1")
    profile_context = SimpleNamespace(state={}, invocation_id="old-invocation")
    intake.save_nonprofit_profile(profile_context, organization_type="nonprofit", project_purpose="food pantry")
    profile_context.state[intake.RESEARCH_EVIDENCE_KEY] = {
        "invocation_id": "old-invocation", "profile_version": 1,
        "details": {str(KNOWN_ID): {"id": KNOWN_ID, "number": KNOWN_NUMBER, "title": "Old grant"}},
        "notices": {str(KNOWN_ID): notices.read_grant_notice(KNOWN_ID, focus=FOCUS)},
    }
    agent, _, _, _ = coordinator(root_turns({}), [
        tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
        tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
        text_turn("The new attempt used an uncataloged synopsis-only candidate."),
    ])

    turns, session = run_session(agent, ["Research again."], state=profile_context.state)

    evidence = session.state[intake.RESEARCH_EVIDENCE_KEY]
    assert evidence["invocation_id"] != "old-invocation"
    assert set(evidence["details"]) == {"9001"}
    assert set(evidence["notices"]) == {"9001"}
    assert SOURCE_URL not in coordinator_text(turns[0])


@pytest.mark.parametrize("updates", [
    {"project_purpose": "after-school tutoring"},
    {"funding_amount_usd": -10},
])
def test_profile_correction_or_rejected_update_clears_saved_notice_evidence(updates):
    context = SimpleNamespace(state={}, invocation_id="profile-turn")
    intake.save_nonprofit_profile(context, organization_type="nonprofit", project_purpose="food pantry")
    context.state[intake.RESEARCH_EVIDENCE_KEY] = {"old": "source evidence"}

    intake.save_nonprofit_profile(context, **updates)

    assert not context.state.get(intake.RESEARCH_EVIDENCE_KEY)


def test_child_research_entry_replaces_previous_attempt_evidence():
    context = evidence_context(invocation_id="old-invocation")
    context.invocation_id = "new-invocation"
    context.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)] = {"status": "success"}

    begin_research(SimpleNamespace(name="opportunity_researcher"), {}, context)
    notice_evidence.begin_notice_research(context)

    evidence = context.state[intake.RESEARCH_EVIDENCE_KEY]
    assert evidence["invocation_id"] == "new-invocation"
    assert evidence["profile_version"] == 1
    assert evidence["details"] == {} and evidence["notices"] == {}


@pytest.mark.parametrize("response", [
    LlmResponse(content=types.Content(role="model", parts=[]), finish_reason=types.FinishReason.STOP),
    LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Partial text")]), partial=True),
    LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Blocked")]), finish_reason=types.FinishReason.SAFETY),
    LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Failure")]), error_code="SYNTHETIC_ERROR"),
    LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Interrupted")]), interrupted=True),
    LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Hidden thought", thought=True)]), finish_reason=types.FinishReason.STOP),
])
def test_required_notice_attempt_does_not_rewrite_errors_empty_or_partial_responses(response):
    context = evidence_context()
    original = response.model_copy(deep=True)

    altered = notice_evidence.ensure_notice_attempts(context, response)
    observed = response if altered is None else altered

    assert observed.content == original.content
    assert not observed.get_function_calls()
    assert not (observed.custom_metadata or {}).get("notice_read_enforced")


def test_stale_attempt_metadata_cannot_force_an_old_notice_read():
    context = evidence_context(invocation_id="old-invocation")
    context.invocation_id = "new-invocation"
    response = LlmResponse(content=text_turn("No current detail fetch has occurred."))

    altered = notice_evidence.ensure_notice_attempts(context, response)
    observed = response if altered is None else altered

    assert not observed.get_function_calls()


def test_source_status_renderer_does_not_reuse_another_attempts_pages():
    context = evidence_context(invocation_id="old-invocation")
    context.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)] = notices.read_grant_notice(KNOWN_ID, focus=FOCUS)
    context.state[intake.RESEARCH_OUTCOME_KEY] = {
        "status": "completed", "invocation_id": "new-invocation", "profile_version": 1,
    }

    rendered = notice_evidence.render_notice_evidence(context.state)

    assert SOURCE_URL not in rendered


def test_parallel_focused_reads_keep_the_union_of_pages_from_the_same_snapshot(install_grants):
    calls = install_grants()
    deadline_focus = "application deadlines state commission"
    funding_focus = "cost sharing matching funds"
    findings = "Deadline and cost-sharing passages were retrieved; eligibility remains unverified."
    agent, root_model, research_model, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        tool_turn(
            ("read_grant_notice", {"opportunity_id": KNOWN_ID, "focus": deadline_focus, "max_excerpts": 2}),
            ("read_grant_notice", {"opportunity_id": KNOWN_ID, "focus": funding_focus, "max_excerpts": 2}),
        ),
        text_turn(findings),
    ])

    turns, session = run_session(agent, ["Read both the deadline and cost-sharing rules."])

    results = tool_responses(turns[0], "read_grant_notice")
    assert len(results) == 2 and all(result["status"] == "success" for result in results)
    # Each tool response keeps its requested budget; aggregation belongs only
    # to saved evidence, so later reads cannot erase earlier page citations.
    assert all(len(result["excerpts"]) <= 2 for result in results)
    expected = {
        excerpt["evidence_id"]: excerpt
        for result in results for excerpt in result["excerpts"]
    }
    saved = session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)]
    assert {item["evidence_id"]: item for item in saved["excerpts"]} == expected
    assert len(saved["excerpts"]) == len(expected)  # No duplicate evidence IDs.
    assert {result["source_sha256"] for result in results} == {saved["source_sha256"]}
    assert {(attempt["focus"], attempt["status"]) for attempt in saved["read_attempts"]} == {
        (deadline_focus, "success"), (funding_focus, "success"),
    }
    pages = {excerpt["page_number"] for excerpt in saved["excerpts"]}
    assert {1, 7, 8} <= pages
    answer = coordinator_text(turns[0])
    assert answer.endswith(findings)
    assert all(f"{SOURCE_URL}#page={page}" in answer for page in pages)
    assert len(root_model.requests) == 2 and len(research_model.requests) == 3
    assert [endpoint for endpoint, _ in calls] == ["fetchOpportunity"]


def test_query_with_no_matching_excerpts_preserves_previous_valid_page_evidence(install_grants):
    install_grants()
    findings = "The later query did not locate evidence for that term; eligibility remains unverified."
    agent, _, research_model, _ = coordinator(root_turns(), [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        tool_turn(("read_grant_notice", {
            "opportunity_id": KNOWN_ID, "focus": "application deadlines state commission", "max_excerpts": 2,
        })),
        tool_turn(("read_grant_notice", {
            "opportunity_id": KNOWN_ID, "focus": "zzzzunfindableterm", "max_excerpts": 2,
        })),
        text_turn(findings),
    ])

    turns, session = run_session(agent, ["Read the deadline rules, then look for an unrelated term."])

    first, later = tool_responses(turns[0], "read_grant_notice")
    assert first["status"] == "success" and first["excerpts"]
    assert later["status"] == "no_matching_excerpts" and later["excerpts"] == []
    assert "does not establish that the rule is absent" in later["message"]
    saved = session.state[intake.RESEARCH_EVIDENCE_KEY]["notices"][str(KNOWN_ID)]
    assert saved["status"] == "success"
    assert saved["last_read_status"] == "no_matching_excerpts"
    assert saved["source_sha256"] == first["source_sha256"] == later["source_sha256"]
    assert saved["excerpts"] == first["excerpts"]
    assert [attempt["status"] for attempt in saved["read_attempts"]] == ["success", "no_matching_excerpts"]
    assert saved["eligibility_status"] == "not_assessed"
    answer = coordinator_text(turns[0])
    assert answer.endswith(findings)
    assert all(f"{SOURCE_URL}#page={item['page_number']}" in answer for item in first["excerpts"])
    # The model still receives the latest query result, not the accumulated
    # success status; it can distinguish an unanswered query from a missing rule.
    latest_statuses = [
        part.function_response.response.get("status")
        for content in research_model.requests[-1].contents for part in content.parts or []
        if part.function_response and part.function_response.name == "read_grant_notice"
    ]
    assert latest_statuses[-1] == "no_matching_excerpts"
    assert len(research_model.requests) == 4
