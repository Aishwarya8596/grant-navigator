"""Run the critic through ADK with a real notice, controlled API data and offline models."""

import json

import pytest

from grant_navigator.eligibility import RULE_IDS
from grant_navigator.tools import intake
from test_eligibility_workflow import (
    KNOWN_ID, REGISTRATION_QUOTE, RESEARCH_FINDINGS,
    draft_turn, finding, install_grants, notice_result, reference, requirement,
    research_turns, root_turns,
)
from test_intake_workflow import (
    ScriptedModel, coordinator, coordinator_text, model_tool_names,
    run_session, text_turn, tool_turn,
)


def review_turn(*findings):
    return text_turn(json.dumps({
        "verdict": "revise" if findings else "approve",
        "reviews": [{"opportunity_id": KNOWN_ID, "reviewed_rule_ids": list(RULE_IDS),
                     "findings": list(findings)}],
    }))


def overlooked_sam(notice):
    return {
        "rule_id": "sam_registration", "kind": "overlooked_evidence",
        "correction": "Compare the stated active SAM registration with the mandatory registration clause on page 8 and cite the clause.",
        "evidence_refs": [reference(notice, REGISTRATION_QUOTE)],
    }


def initial_assessment(notice):
    return draft_turn([finding("applicant_type", "met", ["organization_type"], reference(notice, "nonprofit organizations;"))])


def revised_assessment(notice):
    return text_turn(json.dumps({"decisions": [{"opportunity_id": KNOWN_ID, "requirements": [
        # The critic targeted only SAM. An unsolicited change to an accepted
        # applicant finding must not leak into the final report or its citations.
        {"rule_id": "applicant_type", "status": "needs_verification"},
        finding("sam_registration", "met", ["sam_registration_active"], reference(notice, REGISTRATION_QUOTE)),
    ]}]}))


def source_input_from_request(model, index=0):
    contents = model.requests[index].contents
    assert RESEARCH_FINDINGS not in str(contents)
    texts = [part.text for content in contents for part in content.parts or [] if part.text]
    assert len(texts) == 1, "This independent node should receive only its explicit structured input"
    return json.loads(texts[0])


def test_critic_approves_a_complete_review_in_one_pass(install_grants, notice_result):
    analyst = ScriptedModel(responses=[initial_assessment(notice_result)])
    critic = ScriptedModel(responses=[review_turn()])
    agent, root_model, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst, critic_model=critic)

    turns, session = run_session(agent, ["Investigate this AmeriCorps grant using our stated nonprofit facts."])

    assert {event.author for event in turns[0]} >= {"grant_navigator", "opportunity_researcher", "eligibility_analyst", "evidence_critic"}
    assert len(root_model.requests) == 2 and len(analyst.requests) == len(critic.requests) == 1
    assert model_tool_names(critic.requests[0]) == set()
    assert [name for name, _ in install_grants] == ["fetchOpportunity"]
    payload = source_input_from_request(critic)
    candidate = payload["source_input"]["candidates"][0]
    assert candidate["opportunity"]["opportunity_id"] == KNOWN_ID
    assert candidate["excerpts"] and candidate["source_sha256"] == notice_result["source_sha256"]
    assert payload["assessment"]["decisions"][0]["opportunity_id"] == KNOWN_ID
    outcome = session.state["critic_outcome"]
    assert outcome["status"] == "approved" and outcome["revisions"] == 0
    assert outcome["invocation_id"] == payload["source_input"]["invocation_id"]
    assert outcome["profile_version"] == payload["source_input"]["profile_version"]
    assert len(session.state["critic_history"]) == 1
    assert session.state[intake.ELIGIBILITY_REPORT_KEY]["confirmed_eligible"] is False
    assert coordinator_text(turns[0]).endswith(RESEARCH_FINDINGS)


def test_cited_critique_revises_only_the_target_and_preserves_sources(install_grants, notice_result):
    analyst = ScriptedModel(responses=[initial_assessment(notice_result), revised_assessment(notice_result)])
    issue = overlooked_sam(notice_result)
    critic = ScriptedModel(responses=[review_turn(issue), review_turn()])
    agent, root_model, _, _ = coordinator(
        root_turns({"sam_registration_active": True}), research_turns(), analyst_model=analyst, critic_model=critic,
    )

    turns, session = run_session(agent, ["Compare the stated active SAM registration and nonprofit status with the AmeriCorps notice."])

    assert len(analyst.requests) == len(critic.requests) == len(root_model.requests) == 2
    assert [name for name, _ in install_grants] == ["fetchOpportunity"]
    source = source_input_from_request(analyst, 0)
    revision = source_input_from_request(analyst, 1)
    assert source == {key: revision[key] for key in source}
    assert source == source_input_from_request(critic, 0)["source_input"] == source_input_from_request(critic, 1)["source_input"]
    assert source_input_from_request(critic, 1)["previous_objections"] == revision["revision"]["requested_changes"]
    assert revision["revision"]["previous_assessment"] == source_input_from_request(critic, 0)["assessment"]
    changes = revision["revision"]["requested_changes"]
    assert [(change["opportunity_id"], change["rule_id"]) for change in changes] == [(KNOWN_ID, "sam_registration")]
    assert REGISTRATION_QUOTE in json.dumps(changes)
    history = session.state["critic_history"]
    assert [item["round"] for item in history] == [1, 2]
    assert [item["review"]["verdict"] for item in history] == ["revise", "approve"]
    assert history[0]["draft"] != history[1]["draft"]
    assert history[0]["critic_draft"]["reviews"][0]["findings"][0]["correction"] == issue["correction"]
    previous = {row["rule_id"]: row for row in history[0]["assessment"]["decisions"][0]["requirements"]}
    assert previous["sam_registration"]["status"] == "needs_verification"
    assert requirement(session, "applicant_type") == previous["applicant_type"]
    assert requirement(session, "sam_registration")["status"] == "met"
    assert requirement(session, "sam_registration")["citations"][0]["quote"] == REGISTRATION_QUOTE
    assert session.state["critic_outcome"]["status"] == "approved"
    assert session.state["critic_outcome"]["revisions"] == 1
    assert coordinator_text(turns[0]).endswith(RESEARCH_FINDINGS)


@pytest.fixture
def proposed_nonprofit(notice_result):
    nonprofit_ref = reference(notice_result, "nonprofit organizations;")
    issue = {"rule_id": "applicant_type", "kind": "wrong_condition",
             "correction": "The profile describes a future nonprofit. Keep its current applicant category unresolved.",
             "evidence_refs": [nonprofit_ref]}
    draft = draft_turn([
        finding("applicant_type", "met", ["organization_type"], nonprofit_ref),
        finding("sam_registration", "met", ["sam_registration_active"], reference(notice_result, REGISTRATION_QUOTE)),
    ])
    profile = {"organization_type": "Unincorporated volunteer group considering forming a nonprofit",
               "sam_registration_active": True}
    return profile, draft, review_turn(issue)


@pytest.mark.parametrize("repeat_review", [True, False], ids=["repeat_objection", "approve_unchanged_claim"])
def test_unresolved_challenge_withholds_positive_after_two_revisions(install_grants, proposed_nonprofit, repeat_review):
    profile, draft, objection = proposed_nonprofit
    analyst = ScriptedModel(responses=[draft] * 3)
    critic = ScriptedModel(responses=[objection] + [objection if repeat_review else review_turn()] * 2)
    agent, root_model, _, _ = coordinator(
        root_turns(profile), research_turns(), analyst_model=analyst, critic_model=critic,
    )

    turns, session = run_session(agent, ["Check if our plans to form a nonprofit establish applicant status now."])

    assert len(root_model.requests) == 2 and len(analyst.requests) == len(critic.requests) == 3
    assert len(install_grants) == 1
    assert [item["round"] for item in session.state["critic_history"]] == [1, 2, 3]
    assert session.state["critic_outcome"]["status"] == "revision_limit"
    assert session.state["critic_outcome"]["revisions"] == 2
    first_report = session.state["critic_history"][0]["assessment"]
    old_applicant = next(row for row in first_report["decisions"][0]["requirements"] if row["rule_id"] == "applicant_type")
    assert old_applicant["status"] == "met"
    assert requirement(session, "applicant_type")["status"] == "needs_verification"
    assert requirement(session, "sam_registration")["status"] == "met"
    assert "**Applicant type** (opportunity 363696) needs verification because a critic objection remains unresolved" in coordinator_text(turns[0])
    assert coordinator_text(turns[0]).endswith(RESEARCH_FINDINGS)


def test_final_answer_attributes_unsupported_cost_sharing_to_evidence_check(install_grants):
    draft = draft_turn([{"rule_id": "cost_sharing", "status": "met",
                         "profile_fields": ["americorps_grant_type"]}])
    agent, _, _, _ = coordinator(
        root_turns({"americorps_grant_type": "full_cost_fixed_amount"}), research_turns(),
        analyst_responses=[draft] * 3, critic_responses=[review_turn()] * 3,
    )
    turns, session = run_session(agent, ["Review matching requirements for the selected grant type."])

    assert session.state["critic_outcome"]["status"] == "revision_limit"
    text = coordinator_text(turns[0])
    assert "The AI critic recommended approval of the final draft." in text
    assert "**Cost sharing** (opportunity 363696) needs verification because the automated evidence check found insufficient support" in text
    assert requirement(session, "cost_sharing")["status"] == "needs_verification"


def test_failed_revision_withholds_the_known_disputed_claim(install_grants, proposed_nonprofit):
    profile, draft, objection = proposed_nonprofit
    analyst = ScriptedModel(responses=[draft, text_turn("Malformed revision")])
    critic = ScriptedModel(responses=[objection])
    agent, _, _, _ = coordinator(root_turns(profile), research_turns(), analyst_model=analyst, critic_model=critic)

    turns, session = run_session(agent, ["Review our applicant category."])

    assert len(analyst.requests) == 2 and len(critic.requests) == 1
    assert session.state["critic_outcome"]["status"] == "failed"
    assert session.state["critic_outcome"]["revisions"] == 1
    assert requirement(session, "applicant_type")["status"] == "needs_verification"
    assert requirement(session, "sam_registration")["status"] == "met"
    assert session.state["critic_history"][0]["error"]
    assert coordinator_text(turns[0]).endswith(RESEARCH_FINDINGS)


def test_cosmetic_citation_edit_cannot_clear_an_outstanding_objection(install_grants, proposed_nonprofit):
    profile, draft, objection = proposed_nonprofit
    trimmed_quote = text_turn(draft.parts[0].text.replace("nonprofit organizations;", "nonprofit organizations"))
    agent, _, _, _ = coordinator(
        root_turns(profile), research_turns(), analyst_responses=[draft, trimmed_quote, trimmed_quote],
        critic_responses=[objection, review_turn(), review_turn()],
    )
    _, session = run_session(agent, ["Review our proposed nonprofit status."])
    assert session.state["critic_outcome"]["status"] == "revision_limit"
    assert requirement(session, "applicant_type")["status"] == "needs_verification"


@pytest.mark.parametrize("reply", ["This is not JSON.", '{"verdict":"approve","reviews":[]}'])
def test_invalid_critic_response_is_recorded_as_incomplete_without_spending_revisions(install_grants, notice_result, reply):
    analyst = ScriptedModel(responses=[initial_assessment(notice_result)])
    critic = ScriptedModel(responses=[text_turn(reply)])
    agent, _, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst, critic_model=critic)

    turns, session = run_session(agent, ["Investigate the grant."])

    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["status"] == "completed"
    assert session.state["critic_outcome"]["status"] == "failed"
    assert session.state["critic_outcome"]["revisions"] == 0
    assert len(analyst.requests) == len(critic.requests) == 1
    assert len(session.state["critic_history"]) == 1
    assert "provisional" in coordinator_text(turns[0]).lower()
    assert coordinator_text(turns[0]).endswith(RESEARCH_FINDINGS)


def test_profile_only_correction_clears_earlier_critic_approval(install_grants, notice_result):
    critic = ScriptedModel(responses=[review_turn()])
    root_responses = root_turns() + [
        tool_turn(("save_nonprofit_profile", {"service_area": "Santa Clara County"})),
        text_turn("Your updated service area is saved."),
    ]
    agent, _, _, _ = coordinator(root_responses, research_turns(), analyst_responses=[initial_assessment(notice_result)], critic_model=critic)

    turns, session = run_session(agent, ["Assess this opportunity.", "Save the new service area and stop there."])

    assert session.state[intake.PROFILE_VERSION_KEY] == 2
    assert session.state.get(intake.ELIGIBILITY_REPORT_KEY) is None
    assert not session.state.get("critic_outcome") and not session.state.get("critic_history")
    assert len(critic.requests) == 1 and len(install_grants) == 1
    assert not any(event.author == "evidence_critic" for event in turns[1])


def test_new_invocation_cannot_reuse_approval_for_same_profile(install_grants, notice_result):
    analyst = ScriptedModel(responses=[initial_assessment(notice_result), initial_assessment(notice_result)])
    critic = ScriptedModel(responses=[review_turn(), text_turn("Malformed second review")])
    roots = root_turns() + [tool_turn(("save_nonprofit_profile", {})),
                            tool_turn(("opportunity_researcher", {"request": "Repeat this grant review."}))]
    agent, _, _, _ = coordinator(roots, research_turns() + research_turns(), analyst_model=analyst, critic_model=critic)

    turns, session = run_session(agent, ["Review the grant.", "Review the same grant using our unchanged facts."])

    first = source_input_from_request(critic, 0)["source_input"]
    second = source_input_from_request(critic, 1)["source_input"]
    assert first["profile_version"] == second["profile_version"] == 1
    assert first["invocation_id"] != second["invocation_id"]
    assert session.state["critic_outcome"]["invocation_id"] == second["invocation_id"]
    assert session.state["critic_outcome"]["status"] == "failed"
    assert len(session.state["critic_history"]) == 1
    assert session.state["critic_history"][0]["assessment"]["invocation_id"] == second["invocation_id"]
    assert "accepted" in coordinator_text(turns[0])
    assert "provisional" in coordinator_text(turns[1])
