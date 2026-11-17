"""Exercise intake, handoff guards, and shared state through ADK without a key.

The model's choices are scripted; Grants.gov is replaced at its HTTP boundary.
These tests check application sequencing, not Gemini's choice quality.
"""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest
from google.adk.agents.llm_agent import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import Field

from grant_navigator.agent import opportunity_researcher, root_agent
from grant_navigator.eligibility import RULE_IDS
from grant_navigator.eligibility_workflow import make_eligibility_callback
from grant_navigator.research import RESEARCH_FAILURE_MESSAGE, check_research_result
from grant_navigator.tools import grants_gov, intake


class ScriptedModel(BaseLlm):
    """Return predetermined model turns while retaining the actual ADK inputs."""

    model: str = "offline-scripted-model"
    responses: list[types.Content | LlmResponse] = Field(default_factory=list, exclude=True)
    requests: list = Field(default_factory=list, exclude=True)

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request.model_copy(deep=True))
        assert self.responses, "ADK made an unexpected additional model call"
        response = self.responses.pop(0)
        yield response if isinstance(response, LlmResponse) else LlmResponse(content=response)


class UnresolvedAnalystModel(BaseLlm):
    """Offline default for legacy discovery tests, not a source-quality oracle."""

    model: str = "offline-unresolved-analyst"
    requests: list = Field(default_factory=list, exclude=True)

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request.model_copy(deep=True))
        source_input = json.loads(llm_request.contents[-1].parts[0].text)
        decisions = [{
            "opportunity_id": item["opportunity"]["opportunity_id"],
            "requirements": [{"rule_id": rule, "status": "needs_verification"} for rule in RULE_IDS],
        } for item in source_input["candidates"]]
        yield LlmResponse(
            content=text_turn(json.dumps({"decisions": decisions})),
            finish_reason=types.FinishReason.STOP,
        )


class ApprovingCriticModel(BaseLlm):
    """Script a complete review for earlier tests of intake and eligibility."""

    model: str = "offline-approving-critic"

    async def generate_content_async(self, llm_request, stream=False):
        source_input = json.loads(llm_request.contents[-1].parts[0].text)["source_input"]
        reviews = [
            {"opportunity_id": item["opportunity"]["opportunity_id"],
             "reviewed_rule_ids": list(RULE_IDS), "findings": []}
            for item in source_input["candidates"]
        ]
        yield LlmResponse(content=text_turn(json.dumps({"verdict": "approve", "reviews": reviews})))


def tool_turn(*calls):
    return types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name=name, args=args)) for name, args in calls],
    )


def text_turn(text):
    return types.Content(role="model", parts=[types.Part(text=text)])


def configured_copy(template, model, sub_agents=(), *, analyst_model=None, critic_model=None):
    """Copy production settings, rebuilding ADK's auto-generated child tool.

    Agent.clone() copies the generated AgentTool separately from its sub-agent,
    so reconstruct from public fields to keep it bound to our scripted child.
    """
    child_names = {child.name for child in template.sub_agents}
    settings = {
        name: getattr(template, name)
        for name in type(template).model_fields
        if name not in {"parent_agent", "model", "sub_agents", "tools"}
    }
    # A callback closure can hold an agent that is not in sub_agents. Replace
    # that node too; copying the callback unchanged would call real Gemini.
    callbacks = []
    for callback in template.canonical_before_model_callbacks:
        if hasattr(callback, "analyst_node"):
            offline = analyst_model if analyst_model is not None else UnresolvedAnalystModel()
            node = configured_copy(callback.analyst_node, offline)
            critic = configured_copy(callback.critic_node, critic_model if critic_model is not None else ApprovingCriticModel())
            callback = make_eligibility_callback(node, critic)
        callbacks.append(callback)
    settings["before_model_callback"] = callbacks or None
    tools = [tool for tool in template.tools if getattr(tool, "name", None) not in child_names]
    return Agent(**settings, model=model, tools=tools, sub_agents=list(sub_agents))


def coordinator(root_responses, researcher_responses=(), *, analyst_responses=None, analyst_model=None,
                critic_responses=None, critic_model=None):
    root_model = ScriptedModel(responses=list(root_responses))
    research_model = ScriptedModel(responses=list(researcher_responses))
    child = configured_copy(opportunity_researcher, research_model)
    if analyst_model is None:
        analyst_model = (
            ScriptedModel(responses=list(analyst_responses))
            if analyst_responses is not None else UnresolvedAnalystModel()
        )
    if critic_model is None and critic_responses is not None:
        critic_model = ScriptedModel(responses=list(critic_responses))
    agent = configured_copy(root_agent, root_model, [child], analyst_model=analyst_model, critic_model=critic_model)
    handoff_checks = []
    production_callbacks = list(agent.canonical_before_model_callbacks)

    async def observe_handoff(callback_context, llm_request):
        result = None
        for callback in production_callbacks:
            result = callback(callback_context=callback_context, llm_request=llm_request)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                break
        handoff_checks.append(
            {
                "invocation_id": callback_context.invocation_id,
                "prepared": callback_context.state.get(intake.PREPARED_INVOCATION_KEY),
                "allowed_version": callback_context.state.get(intake.ALLOWED_VERSION_KEY),
                "profile_version": callback_context.state.get(intake.PROFILE_VERSION_KEY),
            }
        )
        return result

    agent.before_model_callback = observe_handoff
    return agent, root_model, research_model, handoff_checks


async def run_turn(runner, session, prompt):
    return [
        event
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        )
    ]


def run_session(agent, prompts, state=None):
    async def scenario():
        runner = InMemoryRunner(agent=agent, app_name="grant_navigator")
        session = await runner.session_service.create_session(
            app_name="grant_navigator", user_id="offline-test-user", state=state or {}
        )
        try:
            turns = [await run_turn(runner, session, prompt) for prompt in prompts]
            final_session = await runner.session_service.get_session(
                app_name="grant_navigator", user_id=session.user_id, session_id=session.id
            )
            return turns, final_session
        finally:
            await runner.close()

    return asyncio.run(scenario())


def tool_responses(events, name):
    return [response.response for event in events for response in event.get_function_responses() if response.name == name]


def coordinator_text(events):
    return "\n".join(
        part.text
        for event in events if event.author == "grant_navigator" and event.content
        for part in event.content.parts if part.text and not part.thought
    )


def model_tool_names(request):
    return {
        declaration.name
        for tool in request.config.tools or []
        for declaration in tool.function_declarations or []
    }


@pytest.fixture
def grant_requests(monkeypatch):
    calls = []

    def fake_post(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint == "search2":
            return {
                "hitCount": 1,
                "oppHits": [{"id": "9001", "number": "OFFLINE-1", "title": "Offline fixture opportunity", "oppStatus": "posted"}],
            }
        assert endpoint == "fetchOpportunity"
        return {
            "id": 9001,
            "opportunityNumber": "OFFLINE-1",
            "opportunityTitle": "Offline fixture opportunity",
            "synopsis": {"synopsisDesc": "Synthetic opportunity for offline orchestration tests."},
        }

    monkeypatch.setattr(grants_gov, "_post_json", fake_post)
    return calls


def test_valid_profile_handoff_shares_state_and_child_events(grant_requests):
    child_summary = (
        "Offline fixture opportunity OFFLINE-1. Full notice verification is needed.\n"
        "Source: https://example.test/opportunity/OFFLINE-1\n"
        "API general deadline: unknown; applicant-specific deadline remains unverified."
    )
    agent, root_model, research_model, checks = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "501(c)(3) nonprofit", "organization_location": "California", "project_purpose": "community volunteer programs"})),
            tool_turn(("opportunity_researcher", {"request": "Discover posted grants using the saved profile."})),
        ],
        [
            tool_turn(("search_grants", {"keyword": "community volunteer programs", "rows": 5})),
            tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
            tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
            text_turn(child_summary),
        ],
    )

    turns, session = run_session(agent, ["We are a California nonprofit running community volunteer programs. Find grants."])

    assert [call[0] for call in grant_requests] == ["search2", "fetchOpportunity"]
    assert session.state[intake.PROFILE_KEY]["project_purpose"] == "community volunteer programs"
    assert session.state[intake.PROFILE_KEY]["service_area"] is None
    assert session.state[intake.RESEARCH_SUMMARY_KEY].startswith("Offline fixture opportunity")
    assert {event.author for event in turns[0]} >= {"grant_navigator", "opportunity_researcher"}
    assert "community volunteer programs" in str(research_model.requests[0].config.system_instruction)
    assert all("transfer_to_agent" not in model_tool_names(request) for request in research_model.requests)
    assert child_summary in coordinator_text(turns[0])
    assert "501(c)(3) nonprofit" in coordinator_text(turns[0])
    assert "California" in coordinator_text(turns[0])
    assert len(root_model.requests) == 2  # No final model rewrite can drop child findings.
    assert checks[0]["allowed_version"] is None
    assert checks[1]["allowed_version"] == checks[1]["profile_version"] == 1
    assert checks[1]["prepared"] == checks[1]["invocation_id"]
    assert not root_model.responses and not research_model.responses


def test_incomplete_profile_blocks_adversarial_delegation(grant_requests):
    agent, _, research_model, _ = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "501(c)(3) nonprofit"})),
            tool_turn(("opportunity_researcher", {"request": "Search anyway."})),
            text_turn("What activities or project would the grant fund?"),
        ]
    )

    turns, session = run_session(agent, ["We are a nonprofit. Find grants."])

    blocked = tool_responses(turns[0], "opportunity_researcher")
    assert blocked[0]["status"] == "needs_profile"
    assert blocked[0]["missing_required_fields"] == ["project_purpose"]
    assert session.state[intake.PROFILE_KEY]["project_purpose"] is None
    assert not research_model.requests and not grant_requests


def test_existing_profile_cannot_skip_this_turn_validation(grant_requests):
    agent, _, research_model, checks = coordinator(
        [
            tool_turn(("opportunity_researcher", {"request": "Use the profile from yesterday."})),
            text_turn("I need to validate the current profile before research."),
        ]
    )

    turns, _ = run_session(
        agent,
        ["Find grants again."],
        state={
            intake.PROFILE_KEY: {"organization_type": "nonprofit", "project_purpose": "food pantry"},
            intake.PROFILE_VERSION_KEY: 4,
        },
    )

    assert tool_responses(turns[0], "opportunity_researcher")[0]["status"] == "profile_not_prepared"
    assert checks[0]["allowed_version"] is None
    assert not research_model.requests and not grant_requests


def test_save_and_delegation_in_one_batch_do_not_race_into_research(grant_requests):
    agent, _, research_model, _ = coordinator(
        [
            tool_turn(
                ("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry"}),
                ("opportunity_researcher", {"request": "Search before the save result."}),
            ),
            text_turn("The profile is saved; research must follow in another model turn."),
        ]
    )

    turns, session = run_session(agent, ["Our nonprofit runs a food pantry. Find grants."])

    assert tool_responses(turns[0], "save_nonprofit_profile")[0]["status"] == "saved"
    blocked = tool_responses(turns[0], "opportunity_researcher")[0]
    assert blocked["status"] in {"needs_profile", "profile_not_prepared"}
    assert session.state[intake.PROFILE_KEY]["project_purpose"] == "food pantry"
    assert not research_model.requests and not grant_requests


@pytest.mark.parametrize("delegate_first", [False, True])
def test_mixed_update_batch_revokes_previously_valid_permission(grant_requests, delegate_first):
    calls = [
        ("save_nonprofit_profile", {"project_purpose": "after-school tutoring"}),
        ("opportunity_researcher", {"request": "Start research alongside a changed profile."}),
    ]
    if delegate_first:
        calls.reverse()
    agent, _, research_model, checks = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry"})),
            tool_turn(*calls),
            text_turn("The changed profile must be researched in a subsequent model turn."),
        ]
    )

    turns, session = run_session(agent, ["Our nonprofit runs a food pantry. Find grants."])

    assert checks[1]["allowed_version"] == 1  # Permission existed before the bad batch.
    blocked = tool_responses(turns[0], "opportunity_researcher")[0]
    assert blocked["status"] == "profile_not_prepared"
    assert "separate steps" in blocked["message"]
    assert session.state[intake.PROFILE_KEY]["project_purpose"] == "after-school tutoring"
    assert not research_model.requests and not grant_requests


def test_blocked_batch_can_recover_in_a_subsequent_model_turn(grant_requests):
    agent, _, research_model, checks = coordinator(
        [
            tool_turn(
                ("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry"}),
                ("opportunity_researcher", {"request": "This simultaneous delegation must be blocked."}),
            ),
            tool_turn(("opportunity_researcher", {"request": "The save result is now available; research the profile."})),
        ],
        [
            tool_turn(("search_grants", {"keyword": "food pantry"})),
            tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
            tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
            text_turn("Research after a corrected handoff."),
        ],
    )

    turns, _ = run_session(agent, ["Find food pantry grants for our nonprofit."])

    delegations = tool_responses(turns[0], "opportunity_researcher")
    assert delegations[0]["status"] == "profile_not_prepared"
    assert checks[1]["allowed_version"] == 1
    assert len(research_model.requests) == 4
    assert "Research after a corrected handoff." in coordinator_text(turns[0])
    assert [endpoint for endpoint, _ in grant_requests] == ["search2", "fetchOpportunity"]


def test_correction_in_later_turn_researches_updated_profile(grant_requests):
    agent, root_model, research_model, checks = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry", "service_area": "San Jose"})),
            tool_turn(("opportunity_researcher", {"request": "Research the current profile."})),
            tool_turn(("save_nonprofit_profile", {"project_purpose": "after-school tutoring"})),
            tool_turn(("opportunity_researcher", {"request": "Research the corrected profile."})),
        ],
        [
            tool_turn(("search_grants", {"keyword": "food pantry", "rows": 5})),
            tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
            tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
            text_turn("First research result for food pantry."),
            tool_turn(("search_grants", {"keyword": "after-school tutoring", "rows": 5})),
            tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
            tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
            text_turn("Second research result for after-school tutoring."),
        ],
    )

    turns, session = run_session(agent, ["Find food pantry grants.", "Correction: the project is after-school tutoring. Find grants for that instead."])

    assert [payload["keyword"] for endpoint, payload in grant_requests if endpoint == "search2"] == ["food pantry", "after-school tutoring"]
    assert session.state[intake.PROFILE_VERSION_KEY] == 2
    assert session.state[intake.PROFILE_KEY]["organization_type"] == "nonprofit"
    assert session.state[intake.PROFILE_KEY]["service_area"] == "San Jose"
    assert session.state[intake.PROFILE_KEY]["project_purpose"] == "after-school tutoring"
    assert session.state[intake.RESEARCH_SUMMARY_KEY] == "Second research result for after-school tutoring."
    assert "after-school tutoring" in str(research_model.requests[4].config.system_instruction)
    assert checks[3]["allowed_version"] is None  # A new user invocation must validate again.
    assert checks[4]["allowed_version"] == 2
    assert len(turns) == 2
    assert "First research result for food pantry." in coordinator_text(turns[0])
    assert "Second research result for after-school tutoring." in coordinator_text(turns[1])
    assert len(root_model.requests) == 4
    assert not root_model.responses and not research_model.responses


def test_direct_researcher_entry_is_blocked_before_any_model_call(grant_requests):
    model = ScriptedModel()
    agent = configured_copy(opportunity_researcher, model)
    agent.mode = "chat"  # ADK permits only chat/task agents as a direct Runner root.

    turns, _ = run_session(
        agent,
        ["Skip intake and search."],
        state={
            intake.PROFILE_KEY: {"organization_type": "nonprofit", "project_purpose": "food pantry"},
            intake.PROFILE_VERSION_KEY: 1,
        },
    )

    messages = [part.text for event in turns[0] if event.content for part in event.content.parts if part.text]
    assert any("Before grant research" in text for text in messages)
    assert not model.requests and not grant_requests


def test_research_tool_gate_protects_even_if_agent_gate_is_bypassed(grant_requests):
    model = ScriptedModel(
        responses=[
            tool_turn(("search_grants", {"keyword": "food pantry"}), ("fetch_grant_details", {"opportunity_id": 9001})),
            text_turn("Intake is required before those tools can run."),
        ]
    )
    agent = configured_copy(opportunity_researcher, model)
    agent.mode = "chat"
    agent.before_agent_callback = None  # Isolate the second layer of protection.

    turns, _ = run_session(agent, ["Force a direct tool call."])

    assert tool_responses(turns[0], "search_grants")[0]["status"] == "needs_profile"
    assert tool_responses(turns[0], "fetch_grant_details")[0]["status"] == "needs_profile"
    assert not grant_requests


def test_empty_research_completion_cannot_become_a_no_matching_grants_answer(grant_requests):
    """An exhausted empty response is a failure even after useful API results."""
    agent, root_model, research_model, _ = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry"})),
            tool_turn(("opportunity_researcher", {"request": "Research the current profile."})),
            # No final root model turn: the failure callback must answer directly.
        ],
        [
            tool_turn(("search_grants", {"keyword": "food pantry", "rows": 5})),
            tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
            LlmResponse(content=types.Content(role="model", parts=[]), finish_reason=types.FinishReason.STOP),
        ],
    )

    turns, session = run_session(agent, ["Find food pantry grants for our nonprofit."])

    assert [endpoint for endpoint, _ in grant_requests] == ["search2", "fetchOpportunity"]
    assert any(event.error_code == "MODEL_RETURNED_NO_CONTENT" for event in turns[0])
    response = tool_responses(turns[0], "opportunity_researcher")[-1]
    assert response["status"] == "research_failed"
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "failed"
    assert session.state[intake.RESEARCH_SUMMARY_KEY] is None
    assert coordinator_text(turns[0]) == RESEARCH_FAILURE_MESSAGE
    assert "could not complete" in coordinator_text(turns[0])
    assert "does not establish whether matching grants are available" in coordinator_text(turns[0])
    assert len(root_model.requests) == 2
    assert len(research_model.requests) == 3


def test_fabricated_researcher_transfer_cannot_execute_the_coordinator(grant_requests):
    agent, root_model, research_model, _ = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry"})),
            tool_turn(("opportunity_researcher", {"request": "Research the current profile."})),
        ],
        [
            tool_turn(("transfer_to_agent", {"agent_name": "grant_navigator"})),
            # ADK reports the unavailable tool to the researcher, then an
            # exhausted empty response still must not invoke the coordinator.
            LlmResponse(content=types.Content(role="model", parts=[]), finish_reason=types.FinishReason.STOP),
        ],
    )

    turns, session = run_session(agent, ["Find food pantry grants for our nonprofit."])

    assert "transfer_to_agent" not in model_tool_names(research_model.requests[0])
    unavailable = tool_responses(turns[0], "transfer_to_agent")
    assert unavailable and unavailable[0].get("error")
    assert not any(event.actions.transfer_to_agent for event in turns[0])
    assert tool_responses(turns[0], "opportunity_researcher")[-1]["status"] == "research_failed"
    assert coordinator_text(turns[0]) == RESEARCH_FAILURE_MESSAGE
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "failed"
    assert len(root_model.requests) == 2
    assert not grant_requests


def test_research_failure_does_not_prevent_a_new_turn_from_succeeding(grant_requests):
    agent, root_model, research_model, _ = coordinator(
        [
            tool_turn(("save_nonprofit_profile", {"organization_type": "nonprofit", "project_purpose": "food pantry"})),
            tool_turn(("opportunity_researcher", {"request": "Research the current profile."})),
            tool_turn(("save_nonprofit_profile", {})),
            tool_turn(("opportunity_researcher", {"request": "Try researching again for the same profile."})),
        ],
        [
            LlmResponse(content=types.Content(role="model", parts=[]), finish_reason=types.FinishReason.STOP),
            tool_turn(("search_grants", {"keyword": "food pantry", "rows": 5})),
            tool_turn(("fetch_grant_details", {"opportunity_id": 9001})),
            tool_turn(("read_grant_notice", {"opportunity_id": 9001})),
            text_turn("Recovered research result OFFLINE-1. Eligibility needs notice verification."),
        ],
    )

    turns, session = run_session(agent, ["Find food pantry grants.", "Please try the grant research again."])

    assert coordinator_text(turns[0]) == RESEARCH_FAILURE_MESSAGE
    assert "Recovered research result OFFLINE-1. Eligibility needs notice verification." in coordinator_text(turns[1])
    assert RESEARCH_FAILURE_MESSAGE not in coordinator_text(turns[1])
    assert session.state[intake.RESEARCH_SUMMARY_KEY].startswith("Recovered research result")
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] != "failed"
    assert len(root_model.requests) == 4
    assert not root_model.responses and not research_model.responses
    assert [endpoint for endpoint, _ in grant_requests] == ["search2", "fetchOpportunity"]


@pytest.mark.parametrize("raw_result", [
    None,
    "",
    "   ",
    {"result": None},
    {"result": ""},
    "Error running sub-agent: Synthetic failure",
    "Error validating input: Synthetic failure",
    {"error": "Synthetic failure"},
    {"status": "error", "message": "Synthetic failure"},
])
def test_parent_guard_classifies_raw_empty_and_error_results_as_failed(raw_result):
    context = SimpleNamespace(
        state={
            intake.RESEARCH_SUMMARY_KEY: "Stale earlier summary",
            intake.PROFILE_VERSION_KEY: 1,
        },
        invocation_id="current-test-invocation",
    )
    tool = SimpleNamespace(name="opportunity_researcher")

    result = check_research_result(tool, {}, context, raw_result)

    assert result["status"] == "research_failed"
    assert context.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "failed"
    assert context.state[intake.RESEARCH_SUMMARY_KEY] is None


@pytest.mark.parametrize("status", ["needs_profile", "profile_not_prepared"])
def test_parent_guard_keeps_blocked_intake_distinct_from_failed_research(status):
    context = SimpleNamespace(state={}, invocation_id="current-test-invocation")
    blocked = {"status": status, "ready_for_research": False}
    result = check_research_result(SimpleNamespace(name="opportunity_researcher"), {}, context, blocked)

    assert result is None or result == blocked
    assert context.state.get(intake.RESEARCH_OUTCOME_KEY, {}).get("status") != "failed"


@pytest.mark.parametrize("raw_result", [
    "Candidate OFFLINE-1 requires full-notice verification.",
    {"result": "Candidate OFFLINE-1 requires full-notice verification."},
])
def test_parent_guard_accepts_delivered_text_and_its_adk_wrapper(raw_result):
    context = SimpleNamespace(
        state={intake.PROFILE_VERSION_KEY: 1},
        invocation_id="current-test-invocation",
    )

    result = check_research_result(
        SimpleNamespace(name="opportunity_researcher"), {}, context, raw_result
    )

    assert result is None
    assert context.state[intake.RESEARCH_SUMMARY_KEY] == "Candidate OFFLINE-1 requires full-notice verification."
    assert context.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "completed"
