# Output examples

This directory preserves selected actual runs for the final submission and
presentation. It contains the original single-agent example, a three-turn
intake/research example, an observed handoff failure and retest, and full-notice
evidence. Analyst-stage examples must retain their own configuration and
verification scope rather than inherit an earlier run's success status.
Source fixtures under `data/` are reference data, not generated output examples.

| Example | Status | Evidence |
|---|---|---|
| [Community volunteer grant discovery](01-community-volunteer-search.md) | Observed November 10, 2026; one agent with two tools | Exact prompt, tool arguments, generated response, and trace screenshot |
| [Structured intake and researcher handoff](02-structured-intake-and-handoff.md) | Observed November 12, 2026; two agents | Missing-input questions, live research, profile correction, selected JSON evidence, and an earlier extraction mistake |
| [Empty-result handoff failure](03-empty-result-handoff.md) | Observed November 12, 2026, before the latest reliability fix | Successful grant API calls, unexpected nested transfer, empty model response, `null` researcher result, and unsupported no-match answer |
| [Handoff recovery retest](04-handoff-recovery-retest.md) | Observed November 12, 2026, after the reliability fixes | Missing-input questions, two completed research requests, final-answer preservation, and an earlier rewrite omission |
| [Full-notice evidence](05-full-notice-evidence.md) | Observed November 13, 2026; three scenarios completed, the third after a quota cooldown | Reviewed PDF download, page-linked excerpts, explicit missing-source status, and preserved signature/quota observations |
| [Eligibility analyst](06-eligibility-analyst.md) | Observed November 13, 2026; two targeted live scenarios passed | Three runtime authors, raw/accepted reports, unknown facts, a fresh profile correction, a selected-option conflict, and earlier schema failures |
| No suitable match after full screening | Planned | Capture source-backed exclusions and refusal to fill the shortlist with unsupported candidates |
| Unavailable source or API failure | Planned for the final workflow | Capture recovery or a clear unresolved status |
| [Critic review and correction](07-critic-review.md) | Four-agent milestone | Recorded live behavior and a controlled ADK correction with the original finding, source passage, targeted revision and recheck |

For each new example, record the date, scenario, model/configuration, input,
relevant sources, observed tool sequence, final output, expected behavior, and
review notes. Label simulated failures and frozen-data runs explicitly. Avoid
claiming a final eligibility decision before the supporting notice is checked.

Preserved analyst scenarios (also usable as demo prompts):

1. **Missing facts:** Use the original California 501(c)(3) community-volunteer
   profile and target AmeriCorps opportunity 363696 so the reviewed notice is
   available. Preserve the unknown service area, registration/mechanism facts,
   source-currentness limit, and follow-up questions.
2. **Selected-option conflict:** Add that the organization is a new AmeriCorps
   applicant seeking a full-cost fixed-amount grant, with active SAM and valid
   UEI readiness. With the page 8 exclusion quote, preserve a conflict scoped
   to the selected mechanism rather than a rejection of every grant type in
   the notice. Do not collect or publish the actual UEI.

The [frozen validation benchmark](../docs/evaluation.md) uses constructed drafts
and saved source text. Its JSON results belong to evaluation evidence, not a
captured model-generated conversation or a user study. The critic comparison
and final ranked shortlist examples remain planned.

Learning and challenges are maintained in [the learning log](../docs/learning-log.md).

[08 — Ranked shortlist](08-ranked-shortlist.md) compares three fictional opportunities with an expected order set before implementation.
