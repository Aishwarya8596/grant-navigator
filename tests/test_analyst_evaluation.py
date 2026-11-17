"""The frozen guardrail benchmark must detect unsafe accepted findings."""

from copy import deepcopy
import json

import pytest

from grant_navigator.eligibility import validate_eligibility_report
from scripts import evaluate_analyst


@pytest.fixture(scope="module")
def dataset():
    return evaluate_analyst.load_cases()


@pytest.fixture(scope="module")
def report(dataset):
    return evaluate_analyst.evaluate_cases(dataset)


def case_by_id(report, case_id):
    return next(case for case in report["cases"] if case["id"] == case_id)


def requirement(case, rule):
    return next(item for item in case["accepted_report"]["decisions"][0]["requirements"] if item["rule_id"] == rule)


def test_frozen_cases_are_scoped_as_guardrails_not_model_quality(dataset, report):
    expected_cases = len(dataset["cases"])
    assert expected_cases > 0
    assert expected_cases == len({case["id"] for case in dataset["cases"]})
    assert report["counts"]["passed_cases"] == report["counts"]["cases"] == expected_cases
    assert report["evaluation_kind"] == "analyst_validation_guardrails"
    assert report["llm_predictions_evaluated"] is False
    assert report["independent_expert_labels"] is False
    assert report["source_notice_count"] == 1
    assert report["source"]["currentness_verified"] is False
    assert report["source"]["notice_review_complete"] is False
    assert all(case["accepted_report"]["confirmed_eligible"] is False for case in report["cases"])
    assert all(case["accepted_report"]["semantic_review_complete"] is False for case in report["cases"])
    assert report["counts"]["unsupported_met_attempts"] > 0
    assert report["counts"]["unsupported_met_accepted"] == 0
    assert report["counts"]["false_global_exclusions"] == 0
    assert report["counts"]["adversarial_citation_cases"] == report["counts"]["adversarial_citations_rejected"] == 2
    assert report["counts"]["emitted_citations"] == report["counts"]["grounded_emitted_citations"] > 0


def test_readiness_and_selected_mechanism_have_different_scopes(report):
    conflict = case_by_id(report, "new_applicant_full_cost_conflict")["accepted_report"]["decisions"][0]
    assert conflict["overall_status"] == "blocking_issue"
    assert conflict["blocking_scope"] == "selected_grant_type"
    sam = case_by_id(report, "sam_inactive_readiness")
    assert requirement(sam, "sam_registration")["status"] == "not_met"
    assert sam["accepted_report"]["decisions"][0]["overall_status"] == "needs_verification"
    fixed = case_by_id(report, "fixed_amount_no_match_exclusion")
    assert requirement(fixed, "cost_sharing")["status"] == "met"
    assert requirement(fixed, "cost_sharing")["applicability"] == "does_not_apply"
    past = case_by_id(report, "past_general_api_date_is_not_applicant_exclusion")
    assert past["accepted_report"]["decisions"][0]["general_deadline"]["status"] == "past"
    assert requirement(past, "deadline")["status"] == "needs_verification"


def test_evaluation_detects_a_regressed_validator_instead_of_trusting_its_labels(dataset):
    def regressed(draft, inputs):
        actual = validate_eligibility_report(draft, inputs)
        decision = actual.decisions[0]
        if inputs.invocation_id.endswith("forged_cross_opportunity_evidence"):
            rows = [
                row.model_copy(update={"status": "met"}) if row.rule_id == "applicant_type" else row
                for row in decision.requirements
            ]
            decision = decision.model_copy(update={"requirements": rows})
        if inputs.invocation_id.endswith("sam_inactive_readiness"):
            decision = decision.model_copy(update={"overall_status": "blocking_issue", "blocking_scope": None})
        return actual.model_copy(update={"decisions": [decision]})

    broken = evaluate_analyst.evaluate_cases(dataset, validator=regressed)
    assert broken["counts"]["passed_cases"] == len(dataset["cases"]) - 2
    assert broken["counts"]["unsupported_met_accepted"] == 1
    assert broken["metrics"]["unsupported_met_acceptance_rate"] > 0
    assert broken["counts"]["false_global_exclusions"] == 1
    assert case_by_id(broken, "forged_cross_opportunity_evidence")["passed"] is False
    assert case_by_id(broken, "sam_inactive_readiness")["passed"] is False


def test_a_bad_source_label_stops_setup_instead_of_counting_a_model_miss(dataset):
    broken = deepcopy(dataset)
    selector = broken["evidence_selectors"]["nonprofit_category"]
    selector["quote"] = "This quotation was deliberately invented and is absent from the notice."
    selector["focus"] = "zzyzxunmatchablefixture"
    with pytest.raises(evaluate_analyst.FrozenEvidenceError, match="does not match"):
        evaluate_analyst.evaluate_cases(broken)


def test_missing_local_pdf_does_not_trigger_a_network_download(dataset, tmp_path):
    fixture = json.loads((evaluate_analyst.PROJECT_ROOT / dataset["source"]["fixture"]).read_text())
    fixture["full_notice"]["local_path"] = str(tmp_path / "missing.pdf")
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))
    missing = deepcopy(dataset)
    missing["source"]["fixture"] = str(fixture_path)
    with pytest.raises(evaluate_analyst.FrozenEvidenceError, match="no download is attempted"):
        evaluate_analyst.evaluate_cases(missing)


def test_cli_writes_a_reviewable_report_and_states_its_limits(dataset, tmp_path, capsys):
    output = tmp_path / "guardrail-report.json"
    assert evaluate_analyst.main(["--output", str(output)]) == 0
    written = json.loads(output.read_text())
    assert written["evaluation_kind"] == "analyst_validation_guardrails"
    assert written["llm_predictions_evaluated"] is False
    assert len(written["cases"]) == len(dataset["cases"])
    assert "does not measure raw model quality" in capsys.readouterr().out


def test_duplicate_case_ids_cannot_silently_reweight_the_dataset(dataset, tmp_path):
    duplicated = deepcopy(dataset)
    duplicated["cases"][1]["id"] = duplicated["cases"][0]["id"]
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps(duplicated))
    with pytest.raises(ValueError, match="unique"):
        evaluate_analyst.load_cases(path)
