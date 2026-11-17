# Evaluation: analyst validation stage

This project needs separate evidence for source access, analyst reasoning,
critic benefit, and usefulness to people. The benchmark implemented here checks
the analyst's **validation boundary**. It does not run Gemini or measure the
quality of the analyst model's predictions.

## What runs now

From the project root:

```bash
uv run python -m scripts.evaluate_analyst
```

The command reads the existing local AmeriCorps PDF, resolves page-bound quotes
through the real notice reader, constructs developer-authored draft hypotheses,
and passes them to `validate_eligibility_report`. No model key or network is
required. If the frozen PDF is absent or its checksum changes, setup stops
rather than downloading a different source or silently changing the labels.

Inputs: [17 frozen cases](../evaluation/analyst_cases.json).  
Output: [reviewable JSON report](../evaluation/results/analyst-guardrails.json).

Use `--output PATH` to write a separate report. Exit status is 0 when all cases
meet their expected checks, 1 when an evaluation comparison fails, and 2 when
the dataset or frozen source cannot be loaded safely.

## Dataset and label scope

The source is the saved November 10, 2026 AmeriCorps notice for opportunity
363696, number `AC-08-28-26`. Its SHA256 is stored with the cases. The default
assessment date is frozen at November 13, 2026; the past-date case explicitly
uses January 14, 2027. These are test dates, not claims about present deadlines.

The labels are **developer-curated**, with page references and a rationale in
each case. They have not been independently validated by a grant expert.
Drafts are constructed hypotheses, including deliberate errors; they are not
captured LLM outputs. Unavailable-source and forged-citation cases are explicit
simulations, while their surrounding source text comes from the saved notice.

The 17 cases cover:

- Unknown service area despite a California headquarters.
- Explicit single-state and multi-state plans and submission routes, including
  genuine quotations whose geographical condition does not apply to the profile.
- SAM and UEI readiness, including reported false values.
- The restriction on a new applicant's selected full-cost fixed-amount option.
- Matching requirements that differ between cost-reimbursement and fixed-amount grants.
- A past general API date with an unverified applicant-specific deadline.
- Cross-opportunity references, invented quotations, and unavailable notice evidence.

Every input keeps source currentness and complete notice review unverified.
Overall outcomes therefore remain `needs_verification`, except a supported
conflict scoped to the **selected grant type**. A readiness gap is not a blanket
exclusion from the funding opportunity. No report can claim confirmed eligibility.

## Metrics and their limits

| Metric | What it checks | What it does not establish |
|---|---|---|
| Guardrail case pass rate | All specified comparisons in each frozen case | Raw model accuracy or probability of finding a useful grant |
| Targeted rule status accuracy | Expected `met`, `not_met`, or `needs_verification` labels for the checks targeted by each fixture | Complete coverage of every requirement in the notice |
| Unsupported `met` acceptance | Whether deliberately overoptimistic targeted findings survive validation | Every possible semantic error |
| False global exclusion rate | Whether a readiness or selected-mechanism issue becomes a whole-opportunity block | The real-world error rate across different grants |
| Adversarial citation rejection | Rejection of a wrong evidence ID or invented quotation | Whether every correctly quoted passage logically proves a claim |
| Emitted citation integrity | Matching opportunity evidence, source hash, page, URL, and quote substring | Independent expert review of interpretation |
| Required question presence | Whether specified unresolved checks include a follow-up question | Whether a user finds every question clear or useful |
| Targeted unknown rate and resolved fraction | The mix of resolved and unresolved checks in these partial fixtures | The agent's abstention rate or coverage on actual user requests |

Only the targeted labels are scored. The validator adds other mandatory checks
as unresolved when these deliberately partial drafts omit them. Reporting those
additional rows as failed model predictions would confuse fixture design with
model behavior.

The JSON includes each expected-versus-actual comparison, accepted report,
validation issue codes, source scope, and limitations. It records hashes of the
case data, validator code, and evaluation code so a report can be tied to the
versions that produced it. Rerun after changing those inputs. Tests also run a
deliberately regressed validator: accepting a forged positive finding and
turning inactive SAM into a global block must lower the benchmark result.
This checks that the evaluator can detect failures rather than merely repeat
the validator's own success labels.

## Critic workflow evidence

The four-agent workflow has a controlled ADK Runner example that starts with
a stated active SAM registration and an unresolved registration check. The
scripted critic points to the relevant notice passage. The revised assessment
cites that passage and records the registration requirement as met on the
stated facts. The example preserves both assessments and the critique.
[Recorded correction](../examples/07-critic-review.md)

Regression tests also exercise an immediate approval, an invalid review,
an ignored correction, the two-revision limit, and changes to the user's
profile. They verify how the workflow handles these choices. Measuring how
often Gemini makes a helpful correction requires the held-out cases below.

## Work still needed for final project evaluation

1. Broaden the reviewed notice corpus so results are not dominated by one grant.
2. Create held-out organization scenarios and have expected findings checked
   against complete sources by a person with relevant knowledge.
3. Run the actual analyst model against those cases. Score rule-level results,
   unsupported positive claims, false exclusions, source support, follow-up
   questions, and missing-information handling. Record unknown-rate alongside
   accuracy so an always-uncertain agent does not appear successful.
4. Compare the same cases with and without the implemented critic.
   Use the recorded initial assessment, individual critiques, revisions, and
   final report to count errors fixed, new errors introduced, unchanged errors,
   added model calls, and time. A higher approval rate alone cannot show
   whether users received better guidance.
5. Ask 3-5 users or proxies to perform a grant-finding task. Compare correctness,
   next-action clarity, time, and confidence with ordinary Grants.gov search.
6. Track model requests, latency, quota failures, and recovery per completed
   user task. A single prompt can require multiple model calls.

The [first shortlist scenario](../examples/08-ranked-shortlist.md) exercises the fit rubric.
Top-three relevance across independent profiles still needs evaluation. None of these checks estimate award-winning
probability or replace an applicant's confirmation of the current official rules.
