"""Frozen classroom ordering and failure modes at the final user-facing callback."""
import json
from pathlib import Path

from grant_navigator.eligibility import EligibilityDraft
from grant_navigator.eligibility_workflow import build_analyst_input
from grant_navigator.ranking import rank_candidates
from grant_navigator.tools import grants_gov
from test_intake_workflow import coordinator, coordinator_text, run_session, text_turn, tool_turn, ScriptedModel
from test_eligibility_workflow import root_turns
from grant_navigator.eligibility import RULE_IDS


CASE = json.loads((Path(__file__).resolve().parents[1] / "evaluation/ranking_case.json").read_text())


def test_three_grant_order_in_final_adk_response(monkeypatch):
    candidates = CASE["candidates"]
    by_id = {row["id"]: row for row in candidates}
    def fetch(endpoint, args):
        row = by_id[args["opportunityId"]]
        return {"id": row["id"], "opportunityNumber": str(row["id"]), "opportunityTitle": row["title"],
                "synopsis": {"synopsisDesc": row["description"], "awardFloor": row["award_floor"],
                             "awardCeiling": row["award_ceiling"]}}
    monkeypatch.setattr(grants_gov, "_post_json", fetch)
    research, drafts, reviews = [], [], []
    for row in candidates:
        oid = row["id"]
        research.extend([tool_turn(("fetch_grant_details", {"opportunity_id": oid})),
                         tool_turn(("read_grant_notice", {"opportunity_id": oid}))])
        # Script the analyst's extraction. Only the quoted words vary between candidates.
        fits = [{"dimension": dim, "assessment": "supports", "synopsis_quote": phrase}
                for dim, phrase in [("purpose", "After-school tutoring"), ("beneficiaries", "middle school students"),
                                    ("service_area", "Alameda County"), ("timing", "starting in fall 2027")]
                if phrase in row["description"]]
        drafts.append({"opportunity_id": oid, "fit_evidence": fits, "requirements": [
            {"rule_id": rule, "status": "needs_verification"} for rule in RULE_IDS]})
        reviews.append({"opportunity_id": oid, "reviewed_rule_ids": list(RULE_IDS), "findings": []})
    research.append(text_turn("Research complete."))
    agent, *_ = coordinator(root_turns(CASE["profile"]), research,
                            analyst_model=ScriptedModel(responses=[text_turn(json.dumps({"decisions": drafts}))]),
                            critic_model=ScriptedModel(responses=[text_turn(json.dumps({"verdict": "approve", "reviews": reviews}))]))
    turns, session = run_session(agent, ["Compare these three grants for our tutoring project."])
    ranked = session.state["grant_shortlist"]["ranked"]
    assert [row["id"] for row in ranked] == CASE["expected_order"]
    assert [row["points"] for row in ranked] == [100, 75, 40]
    assert ranked[1]["unknown"] == ["Service area", "Project timing"]
    assert "outside" in ranked[2]["conflicts"][0]
    answer = coordinator_text(turns[0])
    assert answer.index("Alameda After-School Partnerships") < answer.index("Regional Learning Grants") < answer.index("Community Learning Microgrants")
    # A quote belonging only to the first grant cannot place the second grant.
    from types import SimpleNamespace
    from grant_navigator.eligibility import EligibilityReport
    inputs = build_analyst_input(SimpleNamespace(state=session.state, invocation_id=session.state["grant_shortlist"]["invocation_id"]))
    report = EligibilityReport.model_validate(session.state["eligibility_analysis"])
    drafts[0]["fit_evidence"][0]["synopsis_quote"] = "in Alameda County is supported"
    report.decisions[-1].blocking_scope = "selected_grant_type"
    result = rank_candidates(inputs, EligibilityDraft(decisions=drafts), report)
    assert [item["id"] for item in result["ranked"]] == [93003]
    assert any("selected grant type" in text for item in result["held"] for text in item["hold"])
