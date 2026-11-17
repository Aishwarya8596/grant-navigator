"""Exercise the analyst stage in ADK with offline models and source facts.

The saved notice is genuine; API results and model decisions are controlled.
These verify handoff safety and grounding, not final eligibility or live-model
judgment quality.
"""

import json

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field
import pytest

from grant_navigator.research import RESEARCH_FAILURE_MESSAGE
from grant_navigator.eligibility import RULE_IDS
from grant_navigator.tools import grants_gov, intake, notices
from test_intake_workflow import (
    ScriptedModel, coordinator, coordinator_text, model_tool_names,
    run_session, text_turn, tool_responses, tool_turn,
)


KNOWN_ID = 363696
KNOWN_NUMBER = "AC-08-28-26"
RESEARCH_FINDINGS = "RESEARCHER_UNVERIFIED_CLAIM: every grant is eligible. Keep this as research prose, never analyst evidence."
BASE_PROFILE = {
    "organization_type": "501(c)(3) nonprofit", "organization_location": "California",
    "project_purpose": "Community volunteer programs",
}
REGISTRATION_QUOTE = "Applicants must have a valid SAM registration and Unique Entity Identifier to receive an award."


@pytest.fixture(scope="module")
def notice_result():
    result = notices.read_grant_notice(KNOWN_ID)
    assert result["status"] == "success"
    return result


@pytest.fixture
def install_grants(monkeypatch):
    calls = []

    def fake_post(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint == "search2":
            return {"hitCount": 1, "oppHits": [{
                "id": str(KNOWN_ID), "number": KNOWN_NUMBER,
                "title": "Controlled AmeriCorps candidate", "oppStatus": "posted",
                "agencyName": "AmeriCorps", "closeDate": "01/13/2027",
            }]}
        assert endpoint == "fetchOpportunity"
        assert payload == {"opportunityId": KNOWN_ID}
        return {
            "id": KNOWN_ID, "opportunityNumber": KNOWN_NUMBER,
            "opportunityTitle": "Controlled AmeriCorps candidate",
            "responseDate": "Jan 13, 2027 12:00:00 AM EST",
            "agencyDetails": {"agencyName": "AmeriCorps"},
            "synopsis": {
                "agencyName": "Example contact\nGrantor", "synopsisDesc": "Controlled API synopsis, not a full eligibility decision.",
                "applicantTypes": [{"description": "Nonprofits having 501(c)(3) status"}],
                "costSharing": True, "awardFloor": "none", "awardCeiling": "none",
            },
        }

    monkeypatch.setattr(grants_gov, "_post_json", fake_post)
    monkeypatch.setattr(notices, "_download_pdf", lambda source: pytest.fail("Offline tests must not download sources"))
    return calls


def root_turns(updates=None):
    return [
        tool_turn(("save_nonprofit_profile", {**BASE_PROFILE, **(updates or {})})),
        tool_turn(("opportunity_researcher", {"request": "Read the grant notice before assessing requirements."})),
    ]


def research_turns(findings=RESEARCH_FINDINGS):
    return [
        tool_turn(("fetch_grant_details", {"opportunity_id": KNOWN_ID})),
        tool_turn(("read_grant_notice", {"opportunity_id": KNOWN_ID})),
        text_turn(findings),
    ]


def reference(notice, quote):
    excerpt = next(item for item in notice["excerpts"] if quote in item["text"])
    return {"evidence_id": excerpt["evidence_id"], "quote": quote}


def draft_turn(requirements, opportunity_id=KNOWN_ID):
    rows = {item["rule_id"]: item for item in requirements}
    return text_turn(json.dumps({"decisions": [{
        "opportunity_id": opportunity_id,
        "requirements": [rows.get(rule, {"rule_id": rule, "status": "needs_verification"}) for rule in RULE_IDS],
    }]}))


def finding(rule, status, fields, citation):
    return {"rule_id": rule, "status": status, "profile_fields": fields, "evidence_refs": [citation]}


def analyst_payload(model, index=0):
    for content in model.requests[index].contents:
        for part in content.parts or []:
            if not part.text:
                continue
            try:
                payload = json.loads(part.text)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and "profile" in payload and "candidates" in payload:
                return payload
    pytest.fail("The analyst did not receive the structured node input")


def requirement(session, rule):
    report = session.state[intake.ELIGIBILITY_REPORT_KEY]
    return next(item for item in report["decisions"][0]["requirements"] if item["rule_id"] == rule)


def test_source_backed_checks_are_delivered_without_root_rewrite(install_grants, notice_result):
    applicant = reference(notice_result, "nonprofit organizations;")
    registration = reference(notice_result, REGISTRATION_QUOTE)
    analyst_model = ScriptedModel(responses=[draft_turn([
        finding("applicant_type", "met", ["organization_type"], applicant),
        finding("sam_registration", "not_met", ["sam_registration_active"], registration),
        finding("uei", "met", ["has_valid_uei"], registration),
    ])])
    agent, root_model, _, _ = coordinator(
        root_turns({"sam_registration_active": False, "has_valid_uei": True}),
        research_turns(), analyst_model=analyst_model,
    )

    turns, session = run_session(agent, ["Investigate the notice using my stated nonprofit facts."])

    assert {event.author for event in turns[0]} >= {"grant_navigator", "opportunity_researcher", "eligibility_analyst"}
    assert len(root_model.requests) == 2 and len(analyst_model.requests) == 1
    assert all("eligibility_analyst" not in model_tool_names(request) for request in root_model.requests)
    assert all("transfer_to_agent" not in model_tool_names(request) for request in analyst_model.requests)
    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["status"] == "completed"
    report = session.state[intake.ELIGIBILITY_REPORT_KEY]
    assert report["confirmed_eligible"] is False and report["semantic_review_complete"] is False
    assert report["decisions"][0]["overall_status"] == "needs_verification"
    assert requirement(session, "applicant_type")["status"] == "met"
    assert requirement(session, "sam_registration")["status"] == "not_met"
    assert requirement(session, "uei")["status"] == "met"
    assert requirement(session, "source_currentness")["status"] == "needs_verification"
    assert requirement(session, "deadline")["status"] == "needs_verification"
    citation = requirement(session, "applicant_type")["citations"][0]
    assert citation["quote"] == "nonprofit organizations;" and citation["page_number"] == 8
    assert citation["source_sha256"] == notice_result["source_sha256"]
    assert citation["citation_url"].endswith("#page=8")
    answer = coordinator_text(turns[0])
    assert "## Eligibility assessment" in answer and "| Requirement | Finding | Basis |" in answer
    assert "Met on stated facts" in answer and "Not met / action needed" in answer
    assert "[PDF p. 8]" in answer and "2026-11-10" in answer
    assert answer.endswith(RESEARCH_FINDINGS)
    assert [endpoint for endpoint, _ in install_grants] == ["fetchOpportunity"]


def test_analyst_receives_normalized_api_and_pdf_facts_not_research_prose(install_grants):
    analyst_model = ScriptedModel(responses=[draft_turn([])])
    agent, _, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst_model)

    turns, session = run_session(agent, ["Read the grant and assess only supported requirements."])

    details = tool_responses(turns[0], "fetch_grant_details")[0]
    assert details["response_date"] == "2027-01-13"
    assert details["agency"] == "AmeriCorps"
    payload = analyst_payload(analyst_model)
    assert payload["profile"]["service_area"] is None
    candidate = payload["candidates"][0]
    opportunity = candidate["opportunity"]
    assert opportunity["opportunity_id"] == KNOWN_ID
    assert opportunity["applicant_types"] == ["Nonprofits having 501(c)(3) status"]
    assert opportunity["agency"] == "AmeriCorps"
    assert opportunity["award_floor_raw"] == "none" and opportunity["award_floor_usd"] is None
    assert opportunity["api_general_deadline_date"] == "2027-01-13"
    assert opportunity["detail_response_date_raw"] == "Jan 13, 2027 12:00:00 AM EST"
    assert opportunity["api_general_deadline_source"] == "detail_response_date"
    assert opportunity["opportunity_status"] is None
    assert candidate["source_sha256"] and candidate["notice_status"] == "success"
    assert candidate["currentness_verified"] is False and candidate["notice_review_complete"] is False
    assert candidate["excerpts"] and all(item["evidence_id"].startswith(f"notice:{KNOWN_ID}:") for item in candidate["excerpts"])
    assert RESEARCH_FINDINGS not in json.dumps(payload)
    assert RESEARCH_FINDINGS not in str(analyst_model.requests[0].contents)
    assert payload["invocation_id"] == session.state[intake.ELIGIBILITY_OUTCOME_KEY]["invocation_id"]
    assert payload["profile_version"] == session.state[intake.PROFILE_VERSION_KEY]


def test_new_applicant_restriction_blocks_only_selected_grant_type(install_grants, notice_result):
    quote = "New applicants are eligible to apply for cost reimbursement, Education Award Program (EAP), and Professional Corps grants, but are not eligible to apply for full cost fixed amount grants."
    analyst_model = ScriptedModel(responses=[draft_turn([
        finding("grant_type", "met", ["americorps_grant_type", "americorps_new_applicant"], reference(notice_result, quote)),
    ])])
    agent, _, _, _ = coordinator(
        root_turns({"americorps_grant_type": "full_cost_fixed_amount", "americorps_new_applicant": True}),
        research_turns(), analyst_model=analyst_model,
    )

    turns, session = run_session(agent, ["Investigate my selected grant type using the notice."])

    report = session.state[intake.ELIGIBILITY_REPORT_KEY]
    decision = report["decisions"][0]
    assert decision["overall_status"] == "blocking_issue"
    assert decision["blocking_scope"] == "selected_grant_type"
    assert requirement(session, "grant_type")["status"] == "not_met"
    assert report["confirmed_eligible"] is False
    assert "Selected grant-type conflict" in coordinator_text(turns[0])
    assert "other options and overall eligibility remain unverified" in coordinator_text(turns[0])


def test_research_failure_skips_analyst_entirely(install_grants):
    analyst_model = ScriptedModel(responses=[])
    agent, _, _, _ = coordinator(root_turns(), [
        LlmResponse(content=types.Content(role="model", parts=[]), finish_reason=types.FinishReason.STOP),
    ], analyst_model=analyst_model)

    turns, session = run_session(agent, ["Find grants."])

    assert not analyst_model.requests
    assert not any(event.author in {"eligibility_analyst", "evidence_critic"} for event in turns[0])
    assert session.state.get(intake.ELIGIBILITY_REPORT_KEY) is None
    assert coordinator_text(turns[0]) == RESEARCH_FAILURE_MESSAGE


@pytest.mark.parametrize("raw", [
    LlmResponse(content=types.Content(role="model", parts=[]), finish_reason=types.FinishReason.STOP),
    text_turn("This is not structured JSON."), text_turn('{"decisions": "wrong type"}'),
])
def test_invalid_or_empty_analyst_output_keeps_research_and_reports_failure(install_grants, raw):
    analyst_model = ScriptedModel(responses=[raw])
    agent, root_model, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst_model)

    turns, session = run_session(agent, ["Investigate the notice."])

    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["status"] == "failed"
    assert session.state[intake.ELIGIBILITY_REPORT_KEY] is None
    assert session.state[intake.RESEARCH_OUTCOME_KEY]["status"] == "completed"
    assert session.state["critic_outcome"]["status"] == "not_applicable"
    assert session.state["critic_history"] == []
    assert session.state[intake.RESEARCH_SUMMARY_KEY] == RESEARCH_FINDINGS
    answer = coordinator_text(turns[0])
    assert "Eligibility review incomplete" in answer and answer.endswith(RESEARCH_FINDINGS)
    assert "no matching grants" not in answer.casefold()
    assert len(root_model.requests) == 2 and len(analyst_model.requests) == 1


class FailingAnalystModel(BaseLlm):
    model: str = "offline-failing-analyst"
    requests: list = Field(default_factory=list, exclude=True)

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request.model_copy(deep=True))
        raise RuntimeError("Synthetic analyst failure")
        yield


def test_analyst_node_exception_has_honest_failure_and_keeps_findings(install_grants):
    analyst_model = FailingAnalystModel()
    agent, _, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst_model)

    turns, session = run_session(agent, ["Investigate the notice."])

    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["status"] == "failed"
    assert "Eligibility review incomplete" in coordinator_text(turns[0])
    assert coordinator_text(turns[0]).endswith(RESEARCH_FINDINGS)
    assert len(analyst_model.requests) == 1


@pytest.mark.parametrize("bad_reference, expected_issue", [
    ({"evidence_id": "invented-evidence", "quote": "nonprofit organizations;"}, "unknown_evidence_reference"),
    ({"evidence_id": None, "quote": "Every organization is automatically eligible."}, "unsupported_quote"),
])
def test_hallucinated_sources_are_downgraded(install_grants, notice_result, bad_reference, expected_issue):
    bad_reference = dict(bad_reference)
    if bad_reference["evidence_id"] is None:
        bad_reference["evidence_id"] = reference(notice_result, "nonprofit organizations;")["evidence_id"]
    analyst_model = ScriptedModel(responses=[
        draft_turn([finding("applicant_type", "met", ["organization_type"], bad_reference)]),
        draft_turn([]),  # Explicitly leave the unsupported applicant check unresolved after review.
    ])
    agent, _, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst_model)

    _, session = run_session(agent, ["Assess only source-backed requirements."])

    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["status"] == "completed"
    assert requirement(session, "applicant_type")["status"] == "needs_verification"
    assert requirement(session, "applicant_type")["citations"] == []
    original = session.state["critic_history"][0]["assessment"]
    assert expected_issue in {item["code"] for item in original["validation_issues"]}
    assert session.state["critic_outcome"]["status"] == "approved"
    assert len(analyst_model.requests) == 2


def test_invented_candidate_is_omitted_and_actual_candidate_remains_unresolved(install_grants):
    analyst_model = ScriptedModel(responses=[draft_turn([], opportunity_id=999999), draft_turn([])])
    agent, _, _, _ = coordinator(root_turns(), research_turns(), analyst_model=analyst_model)

    _, session = run_session(agent, ["Assess the candidate we actually researched."])

    report = session.state[intake.ELIGIBILITY_REPORT_KEY]
    assert [item["opportunity_id"] for item in report["decisions"]] == [KNOWN_ID]
    assert all(item["status"] == "needs_verification" for item in report["decisions"][0]["requirements"])
    original = session.state["critic_history"][0]["assessment"]
    assert "unknown_candidate" in {item["code"] for item in original["validation_issues"]}
    assert session.state["critic_outcome"]["status"] == "approved"
    assert len(analyst_model.requests) == 2


def test_profile_correction_runs_fresh_analysis(install_grants, notice_result):
    ref = reference(notice_result, REGISTRATION_QUOTE)
    analyst_model = ScriptedModel(responses=[
        draft_turn([finding("sam_registration", "not_met", ["sam_registration_active"], ref)]),
        draft_turn([finding("sam_registration", "met", ["sam_registration_active"], ref)]),
    ])
    roots = root_turns({"sam_registration_active": False}) + [
        tool_turn(("save_nonprofit_profile", {"sam_registration_active": True})),
        tool_turn(("opportunity_researcher", {"request": "Research again using the corrected registration fact."})),
    ]
    agent, root_model, _, _ = coordinator(roots, research_turns()+research_turns(), analyst_model=analyst_model)

    turns, session = run_session(agent, ["Our SAM registration is inactive. Investigate the grant.", "Correction: SAM registration is now active. Reassess it."])

    assert len(analyst_model.requests) == 2 and len(root_model.requests) == 4
    assert analyst_payload(analyst_model, 0)["profile"]["sam_registration_active"] is False
    assert analyst_payload(analyst_model, 1)["profile"]["sam_registration_active"] is True
    assert analyst_payload(analyst_model, 1)["profile_version"] == 2
    assert requirement(session, "sam_registration")["status"] == "met"
    assert session.state[intake.ELIGIBILITY_REPORT_KEY]["profile_version"] == 2
    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["profile_version"] == 2
    assert session.state["critic_outcome"]["status"] == "approved"
    assert session.state["critic_outcome"]["profile_version"] == 2
    assert all(item["assessment"]["profile_version"] == 2 for item in session.state["critic_history"])
    assert "SAM registration is not active" in coordinator_text(turns[0])
    assert "SAM registration is active" in coordinator_text(turns[1])
    assert "SAM registration is not active" not in coordinator_text(turns[1])


def test_no_researched_candidates_skips_analyst():
    analyst_model = ScriptedModel(responses=[])
    findings = "No candidate was researched in this controlled test."
    agent, _, _, _ = coordinator(root_turns(), [text_turn(findings)], analyst_model=analyst_model)

    turns, session = run_session(agent, ["Find candidate grants."])

    assert not analyst_model.requests
    assert session.state[intake.ELIGIBILITY_OUTCOME_KEY]["status"] == "not_applicable"
    assert session.state["critic_outcome"]["status"] == "not_applicable"
    assert session.state[intake.ELIGIBILITY_REPORT_KEY] is None
    assert "## Eligibility assessment" not in coordinator_text(turns[0])
    assert session.state["grant_shortlist"]["ranked"] == []
    assert "This search retrieved no grant details to rank" in coordinator_text(turns[0])
    assert coordinator_text(turns[0]).endswith(findings)
