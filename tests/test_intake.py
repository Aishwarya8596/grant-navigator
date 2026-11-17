"""Profile corrections and intake gates must work without a model or network."""

from types import SimpleNamespace

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from grant_navigator.profile import NonprofitProfile
from grant_navigator.tools.intake import (
    ALLOWED_VERSION_KEY,
    PREPARED_INVOCATION_KEY,
    PROFILE_KEY,
    PROFILE_VERSION_KEY,
    RESEARCH_SUMMARY_KEY,
    block_mixed_profile_research_batch,
    gate_research_delegation,
    gate_research_tools,
    prepare_research_handoff,
    research_gate,
    save_nonprofit_profile,
)


def context(state=None, invocation_id="turn-1"):
    return SimpleNamespace(state={} if state is None else state, invocation_id=invocation_id)


def ready_profile(ctx):
    return save_nonprofit_profile(
        ctx,
        organization_type="501(c)(3) nonprofit",
        organization_location="California",
        project_purpose="Community volunteer programs",
    )


def test_original_demo_facts_allow_discovery_without_inventing_matching_details():
    ctx = context()
    result = ready_profile(ctx)

    assert result["ready_for_research"] is True
    assert result["missing_required_fields"] == []
    assert result["profile"]["organization_location"] == "California"
    for field in ("service_area", "beneficiaries", "funding_amount_usd", "project_timing"):
        assert result["profile"][field] is None
        assert field in result["unknown_matching_fields"]


def test_missing_essentials_return_focused_questions_and_block_research():
    ctx = context()
    result = save_nonprofit_profile(ctx, organization_location="California")
    prepare_research_handoff(ctx, None)

    assert result["missing_required_fields"] == ["organization_type", "project_purpose"]
    assert len(result["follow_up_questions"]) == 2
    assert research_gate(ctx)["status"] == "needs_profile"


def test_partial_update_keeps_previous_facts_and_invalidates_old_research():
    ctx = context()
    ready_profile(ctx)
    ctx.state[RESEARCH_SUMMARY_KEY] = "Earlier research"
    ctx.invocation_id = "turn-2"

    result = save_nonprofit_profile(ctx, service_area="Santa Clara County", beneficiaries="Local seniors")

    assert result["profile"]["organization_type"] == "501(c)(3) nonprofit"
    assert result["profile"]["service_area"] == "Santa Clara County"
    assert result["profile_version"] == 2
    assert ctx.state[RESEARCH_SUMMARY_KEY] is None


def test_explicit_clear_removes_a_previous_fact_and_rechecks_readiness():
    ctx = context()
    ready_profile(ctx)
    result = save_nonprofit_profile(ctx, clear_fields=["project_purpose"])

    assert result["profile"]["project_purpose"] is None
    assert result["ready_for_research"] is False
    assert result["missing_required_fields"] == ["project_purpose"]
    assert result["profile"]["organization_type"] == "501(c)(3) nonprofit"


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), True, "not known"])
def test_invalid_amount_preserves_facts_and_blocks_research_until_corrected(amount):
    ctx = context()
    ready_profile(ctx)
    previous = ctx.state[PROFILE_KEY].copy()
    ctx.state[RESEARCH_SUMMARY_KEY] = "Earlier research"
    result = save_nonprofit_profile(ctx, funding_amount_usd=amount)
    prepare_research_handoff(ctx, None)

    assert result["status"] == "invalid_profile"
    assert ctx.state[PROFILE_KEY] == previous
    assert result["validation_errors"]
    assert ctx.state[RESEARCH_SUMMARY_KEY] is None
    assert research_gate(ctx)["ready_for_research"] is False

    # A no-op or unrelated update cannot silently discard an invalid correction.
    assert save_nonprofit_profile(ctx)["status"] == "invalid_profile"
    assert save_nonprofit_profile(ctx, beneficiaries="Seniors")["status"] == "invalid_profile"

    corrected = save_nonprofit_profile(ctx, funding_amount_usd=10000)
    prepare_research_handoff(ctx, None)
    assert corrected["ready_for_research"] is True
    assert research_gate(ctx) is None


def test_zero_amount_is_not_silently_treated_as_unknown():
    ctx = context()
    ready_profile(ctx)
    result = save_nonprofit_profile(ctx, funding_amount_usd=0)
    assert result["profile"]["funding_amount_usd"] == 0
    assert "funding_amount_usd" not in result["unknown_matching_fields"]


@pytest.mark.parametrize("value", ["  ", "UNKNOWN", "not provided", "None"])
def test_placeholder_text_does_not_satisfy_required_project_purpose(value):
    profile = NonprofitProfile(organization_type="Nonprofit", project_purpose=value)
    assert profile.discovery_status()["missing_required_fields"] == ["project_purpose"]


def test_saved_profile_cannot_bypass_gate_in_same_model_tool_batch():
    ctx = context()
    prepare_research_handoff(ctx, None)
    ready_profile(ctx)

    assert research_gate(ctx)["status"] == "profile_not_prepared"
    prepare_research_handoff(ctx, None)
    assert research_gate(ctx) is None

    # A new save in the permitted batch must revoke permission for the old profile.
    save_nonprofit_profile(ctx, project_purpose="Wetland restoration")
    assert research_gate(ctx)["status"] == "profile_not_prepared"


@pytest.mark.parametrize("order", [
    ["opportunity_researcher", "save_nonprofit_profile"],
    ["save_nonprofit_profile", "opportunity_researcher"],
])
def test_mixed_batch_blocked_even_after_an_earlier_save_and_in_either_order(order):
    ctx = context()
    ready_profile(ctx)
    prepare_research_handoff(ctx, None)
    assert research_gate(ctx) is None
    response = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name=name, args={})) for name in order
    ]))
    block_mixed_profile_research_batch(ctx, response)
    assert research_gate(ctx)["status"] == "profile_not_prepared"
    save_nonprofit_profile(ctx, project_purpose="Wetland restoration")
    assert research_gate(ctx)["status"] == "profile_not_prepared"
    prepare_research_handoff(ctx, None)
    assert research_gate(ctx) is None


def test_explicit_clear_can_resolve_an_invalid_amount_update():
    ctx = context()
    ready_profile(ctx)
    save_nonprofit_profile(ctx, funding_amount_usd=-10)
    result = save_nonprofit_profile(ctx, clear_fields=["funding_amount_usd"])
    assert result["ready_for_research"] is True
    assert result["profile"]["funding_amount_usd"] is None


def test_new_user_turn_requires_profile_validation_before_delegation():
    ctx = context()
    ready_profile(ctx)
    prepare_research_handoff(ctx, None)
    assert research_gate(ctx) is None

    ctx.invocation_id = "turn-2"
    prepare_research_handoff(ctx, None)
    assert research_gate(ctx)["status"] == "profile_not_prepared"
    result = save_nonprofit_profile(ctx)
    prepare_research_handoff(ctx, None)
    assert result["profile_version"] == 1
    assert research_gate(ctx) is None


def test_root_delegation_and_research_tool_both_apply_the_gate():
    ctx = context()
    assert gate_research_delegation(SimpleNamespace(name="save_nonprofit_profile"), {}, ctx) is None
    assert gate_research_delegation(SimpleNamespace(name="opportunity_researcher"), {}, ctx)["status"] == "needs_profile"
    assert gate_research_tools(SimpleNamespace(name="search_grants"), {}, ctx)["status"] == "needs_profile"


def test_invalid_clears_or_field_types_return_errors_without_erasing_facts():
    ctx = context()
    ready_profile(ctx)
    previous = ctx.state[PROFILE_KEY].copy()
    for updates in (
        {"clear_fields": ["not_a_field"]},
        {"clear_fields": "project_purpose"},
        {"clear_fields": ["project_purpose"], "project_purpose": "New activity"},
        {"organization_type": ["nonprofit"]},
    ):
        assert save_nonprofit_profile(ctx, **updates)["status"] == "invalid_profile"
        assert ctx.state[PROFILE_KEY] == previous


def test_separate_sessions_do_not_share_profiles_or_permission():
    first = context()
    ready_profile(first)
    prepare_research_handoff(first, None)
    second = context()

    assert research_gate(first) is None
    assert research_gate(second)["status"] == "needs_profile"
    assert PROFILE_KEY not in second.state
    assert PREPARED_INVOCATION_KEY not in second.state
    assert ALLOWED_VERSION_KEY not in second.state
    assert PROFILE_VERSION_KEY not in second.state


def test_eligibility_facts_are_optional_and_explicit_false_values_survive_updates():
    ctx = context()
    initial = ready_profile(ctx)
    fields = {
        "sam_registration_active", "has_valid_uei", "planned_submission_route",
        "americorps_grant_type", "americorps_new_applicant", "can_meet_match",
    }
    assert fields <= set(initial["unknown_eligibility_fields"])
    assert all(initial["profile"][field] is None for field in fields)
    saved = save_nonprofit_profile(
        ctx, sam_registration_active=False, has_valid_uei=False,
        americorps_new_applicant=False, can_meet_match=False,
        planned_submission_route="state_commission", americorps_grant_type="cost_reimbursement",
    )
    for field in ("sam_registration_active", "has_valid_uei", "americorps_new_applicant", "can_meet_match"):
        assert saved["profile"][field] is False
        assert field not in saved["unknown_eligibility_fields"]
    cleared = save_nonprofit_profile(ctx, clear_fields=["sam_registration_active", "americorps_grant_type"])
    assert cleared["profile"]["sam_registration_active"] is None
    assert cleared["profile"]["americorps_grant_type"] is None
    assert cleared["profile"]["has_valid_uei"] is False


@pytest.mark.parametrize("field, value", [
    ("sam_registration_active", "false"), ("has_valid_uei", 0),
    ("americorps_new_applicant", "yes"), ("can_meet_match", 1),
    ("planned_submission_route", "maybe"), ("americorps_grant_type", "any grant"),
])
def test_invalid_eligibility_facts_do_not_corrupt_the_saved_profile(field, value):
    ctx = context()
    ready_profile(ctx)
    previous = ctx.state[PROFILE_KEY].copy()
    result = save_nonprofit_profile(ctx, **{field: value})
    assert result["status"] == "invalid_profile"
    assert ctx.state[PROFILE_KEY] == previous
    assert research_gate(ctx)["ready_for_research"] is False
