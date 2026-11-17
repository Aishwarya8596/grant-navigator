# Build roadmap

## Milestone 0: Project and source proof

- [x] Set up Python 3.12, pinned dependencies, and an ADK entry point.
- [x] Verify ADK Web discovers `grant_navigator` locally.
- [x] Call the public Grants.gov search and detail endpoints.
- [x] Save a dated example opportunity and a readable full notice.
- [x] Configure the local Gemini key and verify an ADK run calls both Grants.gov tools.

On November 10, 2026, `gemini-flash-latest` returned service-unavailable errors.
The prototype was switched to `gemini-3.5-flash-lite`; a minimal model request
succeeded in 1.4 seconds and a complete ADK search/detail run in 7.3 seconds.
The model now has a 20-second HTTP timeout per attempt and at most three
attempts. Mocked model-failure tests verify recovery from 503, a three-attempt
limit, and no retries for permission errors. These are connection checks;
shortlist relevance and eligibility remain part of the evaluation milestones.

The user's browser trace later showed the old `gemini-flash-latest` was still
active in the long-running server. The project launcher now applies the local
model setting explicitly and prints it at startup. After restarting that
server, the original nonprofit prompt completed through `/run_sse` in 13.5
seconds with two search calls, one detail call, no errors, and
`gemini-3.5-flash-lite` confirmed in the browser trace. Model responses are
buffered to keep SDK retry handling consistent with Web requests. At that
stage, nine tests covered tools and model failure behavior, including streaming
requests.

## Milestone 1: Evidence and matching contracts

- [x] Define a typed nonprofit profile with two required discovery facts:
  organization type and project purpose. Keep unknown matching facts explicit
  and distinguish organization location from project service area.
- [x] Add session-scoped profile saving, partial corrections, explicit clearing,
  input validation, and discovery-readiness checks.
- [x] Define typed reviewed-notice sources and page-excerpt records.
- [x] Extract text from reviewed PDF snapshots with physical page numbers,
  source links, evidence IDs, capture dates, and SHA256 verification.
- [x] Add bounded retrieval of the same approved `.gov` PDF when its saved copy
  is missing, and explicit nonfatal statuses for unavailable or unreadable sources.
- [x] Define typed opportunity records with API provenance and distinguish a
  general API deadline from a verified applicant-specific deadline.
- [x] Define structured analyst input, draft, accepted eligibility report, and
  source-resolved citation records for up to three candidates.
- [x] Add optional SAM/UEI readiness, planned route, selected AmeriCorps grant
  type, new-applicant, and matching-funds facts without expanding the two-fact
  discovery requirement. Store UEI readiness only, not the actual identifier.
- [x] Validate evidence IDs and quote membership against actual current-attempt
  source records; downgrade unsupported findings and preserve unresolved facts.
- [x] Add conservative checks for the curated AmeriCorps notice, including a
  conflict scoped to a new applicant's selected full-cost fixed-amount option.
- [ ] Define the ranked shortlist record and complete broader eligibility gates.
- [ ] Broaden the reviewed notice catalog beyond the initial AmeriCorps example
  and add document discovery or an explicit curation process for more sources.
- [ ] Complete status/deadline screening using verified applicable deadlines and
  source-backed exclusion conditions across the broader notice catalog. The
  implemented API date comparison alone is not an applicant deadline check.
- [x] Rank researched candidates using the initial fit rubric: project purpose
  40, beneficiaries/service area 25, funding amount 20, timing 15. Separate
  cases needing verification from evidence-backed potential matches.

## Milestone 2: Four-agent workflow

- [x] Build the intake coordinator and opportunity researcher as an incremental
  two-agent collaboration. The coordinator calls the researcher after a
  validated profile save; the researcher uses shared session state.
- [x] Gate research on current-invocation profile validation and block mixed
  save/research tool batches before research can begin.
- [x] Handle missing required profile facts and invalid profile updates before
  research starts.
- [x] Prevent the research leaf agent from transferring to its parent or peers;
  its normal return is delivered automatically to the coordinator.
- [x] Retry one empty terminal `STOP` model response without replaying tools.
- [x] Validate the researcher handoff; clear stale summaries and report an
  incomplete run for absent, blank, or recognized error output.
- [x] Add `read_grant_notice` to the researcher; require current opportunity
  details before accepting notice evidence and block a notice read batched
  with a detail fetch.
- [x] Require genuine provider-generated notice calls with native function-
  calling configuration while reads are pending, preserving signed model parts.
  Restore normal generation afterward; reject skipped reads or an exhausted
  six-round limit with an explicit incomplete-research result.
- [x] Keep evidence scoped to the current invocation and profile version, and
  accumulate passages from focused reads of the same reviewed source.
- [x] Build the eligibility analyst as a single-turn structured-output agent.
  Run it after successful research through ADK's dynamic-node API, with source
  facts as input rather than generated researcher prose.
- [x] Validate and render the accepted report before the immutable researcher
  findings, without another coordinator model rewrite. Keep raw output, accepted
  report, and outcome scoped to the current invocation and profile version.
- [x] Build the critic agent to review interpretation and preserve conditions,
  exceptions, missing facts, and the scope of any blocking issue.
- [x] Orchestrate the complete four-agent flow with a supported ADK 2.x
  graph/dynamic workflow.
- [x] Allow at most two targeted analyst/critic revisions and retain before/after
  outputs in the trace.
- [ ] Add full-workflow handling for no relevant results, API failure, and an
  unavailable or unreadable full notice.

The November 12 increments implemented structured intake, the first two roles,
and selected evidence retrieval from reviewed notices. At that stage they did
not assess eligibility, rank candidates, or run a critic. The November 13 analyst
increment below adds initial structured checks; complete and current notice
verification still remains unresolved. The initial catalog supports AmeriCorps
opportunity 363696 only.
The researcher is instructed to keep discovery to three search calls and three
candidate fetches; those search limits are not yet enforced as runtime budgets.

Verification on November 12: 41 offline tests passed, including real ADK runner
tests with a scripted model and mocked Grants.gov responses. A live Web API
session demonstrated missing-input questions, the two-agent search/detail path,
and a correction without another search. The
[saved example](../examples/02-structured-intake-and-handoff.md) also records an
initial extraction error and the revised prompt's successful retest. These
checks establish workflow behavior, not eligibility or ranking accuracy.

A later November 12 user run exposed a different failure: successful search
and detail calls were followed by an unexpected nested agent transfer, an
empty model response, and a `null` researcher result. The coordinator then
reported no matches without evidence for that conclusion. The
[failure example](../examples/03-empty-result-handoff.md) preserves the selected
trace and texts. The transfer preceded the empty response; the trace does not
establish that it caused the provider's empty response.

The current reliability changes address leaf-agent control flow, one empty
response retry, and explicit failure handling. The 41-test count above belongs
to the earlier intake milestone. The coordinator also adds a profile summary
and appends saved researcher findings directly, avoiding another generative
rewrite that could omit them.

Verification of the preceding reliability milestone: **79 offline tests passed**. The
[post-fix live retest](../examples/04-handoff-recovery-retest.md) demonstrated
missing-input questions and two research requests in the same session. Both
research requests returned nonempty findings without transfers or error events;
the coordinator preserved the saved researcher findings. Empty-response retry
and failure reporting were verified with controlled tests. Domain evaluation
remains part of Milestone 3.

The newer notice-reader increment has its own verification and
[full-notice example](../examples/05-full-notice-evidence.md), separate from the
79-test milestone above. A saved snapshot remains dated even when its source
bytes and page references are verified. Source coverage, current amendments,
and the correctness of the model's conclusions need further evaluation.

Implementation began on November 12. The first live check recorded on November
13 verified a 304,842-byte approved-source PDF download with the expected hash,
but the model workflow returned `400 INVALID_ARGUMENT`: an earlier after-model
approach inserted a notice call without Gemini's required thought signature.
The preceding 140-case simulated run did not expose that provider-protocol issue.
The implementation now constrains the next native model call rather than
manufacturing one. New regression checks and a fresh-session live retest are
recorded separately; their outcome is not inferred from the download or
the earlier passing test count.

Notice-stage verification: **144 tests passed** after the native-call correction,
including signed-part preservation, return to normal answering, fail-closed
premature completion, and the six-round limit. Live checks covered the original
search, a page-cited AmeriCorps review, and an uncataloged notice. The third
scenario passed after the reported per-minute quota cooldown. The complete
[example](../examples/05-full-notice-evidence.md) preserves the successful
outputs and both earlier provider-signature and quota observations. These
checks establish retrieval and delivery, not calibrated matching quality.

The November 13 increment implements the third role, `eligibility_analyst`, with eight
checks and conservative accepted outcomes. Unknown service area, registration,
route, or selected mechanism remains unknown. Inactive SAM, missing UEI, or
matching-funds readiness does not automatically exclude an organization from
the whole notice. The only implemented blocking eligibility condition is a
source-backed conflict between a new AmeriCorps applicant and its selected
full-cost fixed-amount grant type. Source currentness and complete review remain
unverified, so no report claims confirmed eligibility.

The analyst appears as a dynamic node in Events/Traces. The initial static agent
tree may still show only the coordinator and researcher. The current attempt
stores its raw model draft, accepted report, and outcome separately; a failed
or newly scoped run cannot display a stale accepted report.

Developer-curated expectations recorded separately from the guard code exposed
a single-state route detector that also matched “more than one state.” The detector was corrected rather
than changing the multi-state expected label to match the code. This is useful
evidence that evaluation can find a real guard error; it is not a measure of
raw model reasoning quality.

The analyst milestone passed **276 offline tests**, **17/17 frozen validation
cases**, and **two targeted live scenarios**. The
[preserved example](../examples/06-eligibility-analyst.md) records unknown-fact
handling, profile corrections, and a selected-option conflict. Earlier SDK/API
schema failures are retained alongside the successful retest. This establishes
the tested workflow paths, not broad model accuracy or user usefulness.

The four-agent critic milestone passed **311 offline tests**. The existing
analyst validation benchmark passed **17/17** frozen cases. The recorded
critic example includes a controlled ADK correction. Broader evaluation will
compare the quality and cost of actual model decisions over held-out profiles.
[Critic example](../examples/07-critic-review.md)

## Milestone 3: Evaluation and class demo

- [x] Add [17 frozen developer-curated validation cases](evaluation.md) using the
  saved AmeriCorps PDF and deliberately constructed analyst drafts. Evaluate
  citation integrity, targeted rule status, unsafe positive acceptance, false
  global exclusion, required questions, and unresolved-check coverage.
- [x] Keep this terminal benchmark separate from Gemini prediction accuracy and
  user research; retain expected-versus-actual checks and source/code hashes.
- [x] Preserve two targeted live analyst scenarios, raw drafts, accepted reports,
  profile versions, and final outputs, plus schema-failure observations.
- [ ] Broaden the source corpus and curate held-out organization scenarios with
  complete-source expected findings checked by a knowledgeable reviewer.
- [ ] Run the actual analyst model on those scenarios. Measure rule correctness,
  unsupported claims, false exclusions, source support, missing facts, and the
  unresolved rate together rather than rewarding an always-uncertain answer.
- [ ] Evaluate top-three relevance and fit scores once ranking is implemented.
- [ ] Compare the same cases with and without the critic; preserve initial
  drafts, specific critiques, bounded revisions, and final accepted results.
- [ ] Ask 3–5 users or proxies to complete a grant-finding task and compare
  correctness, next-action clarity, time, and confidence with Grants.gov search.
- [ ] Demonstrate normal and failure cases in local ADK Web, including tool
  calls, dynamic analyst execution, a selected-option conflict, critic revision,
  and evaluation results. Record model requests, latency, and quota failures
  per completed task.
