"""Run frozen analyst-validation cases without Gemini credentials or a network.

This evaluates the validation boundary with developer-authored hypotheses.
It does not run the analyst LLM or establish real-world grant matching quality.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(PROJECT_ROOT))

from grant_navigator.eligibility import (  # noqa: E402
    AnalystInput,
    EligibilityDraft,
    EligibilityReport,
    validate_eligibility_report,
)
from grant_navigator.opportunities import normalize_opportunity  # noqa: E402
from grant_navigator.tools.notices import read_grant_notice  # noqa: E402


DEFAULT_CASES = PROJECT_ROOT / "evaluation" / "analyst_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation" / "results" / "analyst-guardrails.json"
STATUSES = {"met", "not_met", "needs_verification"}
CITATION_REJECTION_CODES = {"unknown_evidence_reference", "unsupported_quote"}


class FrozenEvidenceError(ValueError):
    """The frozen source or developer label is not reproducible."""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_cases(path: Path = DEFAULT_CASES) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get("schema_version") != 1 or data.get("evaluation_kind") != "analyst_validation_guardrails":
        raise ValueError("Unsupported evaluation dataset schema or kind.")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("The evaluation dataset must contain cases.")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be nonempty and unique.")
    for case in cases:
        expected = case.get("expected", {})
        if not expected.get("check_statuses") or any(
            status not in STATUSES for status in expected["check_statuses"].values()
        ):
            raise ValueError(f"Case {case['id']} must specify valid targeted check labels.")
        if not case.get("label_rationale") or not case.get("basis"):
            raise ValueError(f"Case {case['id']} must identify its label rationale and basis.")
    return data


@lru_cache(maxsize=4)
def _source_bank(serialized_spec: str) -> tuple[dict, dict, dict]:
    """Resolve labels through the real reader, using only an existing local PDF.

    Cache across calls within this process, not across source versions. A
    checksum mismatch or missing quote is a broken benchmark, not a model miss.
    """
    spec = json.loads(serialized_spec)
    source = spec["source"]
    fixture = json.loads((PROJECT_ROOT / source["fixture"]).read_text())
    pdf = PROJECT_ROOT / fixture["full_notice"]["local_path"]
    if not pdf.is_file():
        raise FrozenEvidenceError("The frozen local PDF is missing. Restore it before the offline evaluation; no download is attempted.")
    if sha256(pdf.read_bytes()).hexdigest() != source["sha256"]:
        raise FrozenEvidenceError("The frozen notice checksum changed. Review source labels before rerunning evaluation.")
    if fixture["opportunity"]["id"] != source["opportunity_id"]:
        raise FrozenEvidenceError("The API fixture and notice label refer to different opportunities.")

    notice = read_grant_notice(source["opportunity_id"])
    if notice.get("status") != "success" or notice.get("source_sha256") != source["sha256"]:
        raise FrozenEvidenceError("The reviewed notice is not readable with the expected checksum.")
    bank = {item["evidence_id"]: item for item in notice["excerpts"]}
    selectors = {}
    for name, selector in spec["evidence_selectors"].items():
        quote = _normalize(selector["quote"])

        def matches():
            return [item for item in bank.values() if item["page_number"] == selector["page"] and quote in _normalize(item["text"])]

        found = matches()
        if not found:
            result = read_grant_notice(source["opportunity_id"], selector["focus"], max_excerpts=8)
            if result.get("status") == "success":
                bank.update({item["evidence_id"]: item for item in result["excerpts"]})
            found = matches()
        if not found:
            raise FrozenEvidenceError(f"Frozen label {name!r} does not match a reader excerpt on its declared PDF page.")
        selectors[name] = min(found, key=lambda item: item["evidence_id"])
    return fixture, notice, selectors


def _case_input_and_draft(case: dict, dataset: dict, fixture: dict, notice: dict, selectors: dict):
    profile = {**dataset["baseline_profile"], **case.get("profile_overrides", {})}
    detail = {**deepcopy(fixture["opportunity"]), **case.get("opportunity_overrides", {})}
    opportunity = normalize_opportunity(detail)
    excerpts = {}
    requirements = []
    for check in case["draft_requirements"]:
        selector = dataset["evidence_selectors"][check["selector"]]
        excerpt = selectors[check["selector"]]
        excerpts[excerpt["evidence_id"]] = excerpt
        requirements.append({
            "rule_id": check["rule_id"],
            "status": check["status"],
            "reason": "Developer-authored evaluation hypothesis: " + case["description"],
            "profile_fields": check.get("profile_fields", []),
            "evidence_refs": [{
                "evidence_id": check.get("evidence_id_override", excerpt["evidence_id"]),
                "quote": check.get("quote_override", selector["quote"]),
            }],
        })
    notice_status = case.get("notice_status", "success")
    if notice_status != "success":
        excerpts = {}
    inputs = AnalystInput.model_validate({
        "profile": profile,
        "candidates": [{
            "opportunity": opportunity.model_dump(mode="json"),
            "notice_status": notice_status,
            "currentness_verified": False,
            "notice_review_complete": False,
            "source_sha256": notice["source_sha256"],
            "source_url": notice["source_url"],
            "snapshot_captured_at_utc": notice["snapshot_captured_at_utc"],
            "excerpts": list(excerpts.values()),
        }],
        "as_of_date": case.get("as_of_date", dataset["as_of_date"]),
        "invocation_id": "frozen-evaluation:" + case["id"],
        "profile_version": 1,
    })
    draft = EligibilityDraft.model_validate({
        "decisions": [{
            "opportunity_id": opportunity.opportunity_id,
            "requirements": requirements,
            "summary": "Synthetic draft for validation evaluation; not a captured model prediction.",
        }],
    })
    return inputs, draft


def _citation_is_grounded(citation, candidate) -> bool:
    excerpts = {item.evidence_id: item for item in candidate.excerpts}
    excerpt = excerpts.get(citation.evidence_id)
    return bool(
        excerpt
        and citation.source_sha256 == candidate.source_sha256
        and citation.page_number == excerpt.page_number
        and citation.citation_url == f"{candidate.source_url}#page={excerpt.page_number}"
        and _normalize(citation.quote)
        and _normalize(citation.quote) in _normalize(excerpt.text)
    )


def evaluate_cases(
    dataset: dict,
    *,
    validator: Callable = validate_eligibility_report,
) -> dict:
    """Compare accepted reports with targeted labels, leaving other checks unresolved."""
    spec = json.dumps({"source": dataset["source"], "evidence_selectors": dataset["evidence_selectors"]}, sort_keys=True)
    fixture, notice, selectors = _source_bank(spec)
    results = []
    counts = Counter()
    check_statuses = Counter()
    for case in dataset["cases"]:
        inputs, draft = _case_input_and_draft(case, dataset, fixture, notice, selectors)
        report = validator(draft, inputs)
        if not isinstance(report, EligibilityReport):
            report = EligibilityReport.model_validate(report)
        decision = report.decisions[0]
        actual = {item.rule_id: item for item in decision.requirements}
        proposed = {item.rule_id: item for item in draft.decisions[0].requirements}
        expected = case["expected"]
        comparisons = []

        def compare(label, observed, wanted):
            comparisons.append({"field": label, "expected": wanted, "actual": observed, "passed": observed == wanted})

        compare("overall_status", decision.overall_status, expected["overall_status"])
        if "blocking_scope" in expected:
            compare("blocking_scope", decision.blocking_scope, expected["blocking_scope"])
        global_block = decision.overall_status == "blocking_issue" and decision.blocking_scope != "selected_grant_type"
        compare("global_block", global_block, expected.get("global_block", False))
        counts["false_global_exclusions"] += int(global_block and not expected.get("global_block", False))
        counts["global_exclusion_negative_cases"] += int(not expected.get("global_block", False))
        compare("confirmed_eligible", report.confirmed_eligible, False)
        compare("semantic_review_complete", report.semantic_review_complete, False)
        compare("applicant_specific_deadline_verified", decision.general_deadline.applicant_specific_verified, False)
        if "general_deadline_status" in expected:
            compare("api_general_deadline.status", decision.general_deadline.status, expected["general_deadline_status"])
        for rule, wanted in expected["check_statuses"].items():
            observed = actual.get(rule)
            status = observed.status if observed else "missing"
            compare("requirements." + rule, status, wanted)
            counts["targeted_checks"] += 1
            counts["correct_targeted_checks"] += int(status == wanted)
            check_statuses[status] += 1
            if proposed.get(rule) and proposed[rule].status == "met" and wanted != "met":
                counts["unsupported_met_attempts"] += 1
                counts["unsupported_met_accepted"] += int(status == "met")
        for rule in expected.get("question_rules", []):
            supplied = bool(actual.get(rule) and actual[rule].follow_up_question and actual[rule].follow_up_question.strip())
            compare("follow_up_question." + rule, supplied, True)
            counts["expected_follow_up_questions"] += 1
            counts["follow_up_questions_supplied"] += int(supplied)
        issue_codes = {item.code for item in report.validation_issues}
        if expected.get("citation_rejected"):
            rejected = bool(issue_codes & CITATION_REJECTION_CODES)
            compare("adversarial_citation_rejected", rejected, True)
            counts["adversarial_citation_cases"] += 1
            counts["adversarial_citations_rejected"] += int(rejected)
        invalid_citations = 0
        for requirement in decision.requirements:
            for citation in requirement.citations:
                counts["emitted_citations"] += 1
                valid = _citation_is_grounded(citation, inputs.candidates[0])
                counts["grounded_emitted_citations"] += int(valid)
                invalid_citations += int(not valid)
        compare("ungrounded_emitted_citations", invalid_citations, 0)
        passed = all(item["passed"] for item in comparisons)
        counts["passed_cases"] += int(passed)
        counts["cases"] += 1
        results.append({
            "id": case["id"], "description": case["description"], "basis": case["basis"],
            "passed": passed, "label_rationale": case["label_rationale"],
            "comparisons": comparisons,
            "validation_issue_codes": sorted(issue_codes),
            "accepted_report": report.model_dump(mode="json"),
        })

    def ratio(numerator, denominator):
        return counts[numerator] / counts[denominator] if counts[denominator] else None

    return {
        "schema_version": 1,
        "evaluation_kind": "analyst_validation_guardrails",
        "label_origin": dataset["label_origin"],
        "llm_predictions_evaluated": False,
        "independent_expert_labels": False,
        "source_notice_count": 1,
        "dataset_as_of_date": dataset["as_of_date"],
        "source": dataset["source"],
        "reproducibility": {
            "dataset_sha256": sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest(),
            "validator_code_sha256": sha256((PROJECT_ROOT / "grant_navigator" / "eligibility.py").read_bytes()).hexdigest(),
            "evaluator_code_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "validator_callable": validator.__module__ + "." + validator.__qualname__,
        },
        "counts": dict(counts),
        "metrics": {
            "guardrail_case_pass_rate": ratio("passed_cases", "cases"),
            "targeted_rule_status_accuracy": ratio("correct_targeted_checks", "targeted_checks"),
            "unsupported_met_acceptance_rate": ratio("unsupported_met_accepted", "unsupported_met_attempts"),
            "false_global_exclusion_rate": ratio("false_global_exclusions", "global_exclusion_negative_cases"),
            "adversarial_citation_rejection_rate": ratio("adversarial_citations_rejected", "adversarial_citation_cases"),
            "emitted_citation_integrity_rate": ratio("grounded_emitted_citations", "emitted_citations"),
            "required_question_presence_rate": ratio("follow_up_questions_supplied", "expected_follow_up_questions"),
            "targeted_unknown_rate": check_statuses["needs_verification"] / counts["targeted_checks"] if counts["targeted_checks"] else None,
            "targeted_resolved_fraction": (check_statuses["met"] + check_statuses["not_met"]) / counts["targeted_checks"] if counts["targeted_checks"] else None,
        },
        "targeted_status_counts": dict(check_statuses),
        "limitations": [
            "These are developer-authored partial drafts, not outputs from the analyst model.",
            "The labels cover one dated notice and explicit adversarial/source-failure simulations; they are not independent expert annotations.",
            "Only targeted rule labels are scored; additional mandatory checks remain unresolved in deliberately partial drafts.",
            "Citation integrity verifies identity, page, hash, and quotation, not complete semantic correctness.",
            "Unknown-rate and resolution coverage reflect this fixture distribution, not real-user task performance.",
            "Current notice amendments, complete eligibility, grant ranking, critic benefit, and user usefulness still require separate evaluation.",
        ],
        "cases": results,
    }


def write_report(report: dict, destination: Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        report = evaluate_cases(load_cases(args.cases))
        write_report(report, args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Evaluation setup failed: {exc}\n")
    counts = report["counts"]
    print(f"Analyst validation guardrails: {counts['passed_cases']}/{counts['cases']} developer-curated cases passed.")
    print("This does not measure raw model quality or real-world grant eligibility.")
    print(f"Report: {args.output}")
    return 0 if counts["passed_cases"] == counts["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
