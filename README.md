# Federal Grant Opportunity Navigator

A multi-agent application that helps U.S. nonprofits identify
federal grant opportunities worth investigating. The intended result is a
source-backed shortlist of up to three potential matches, with deadlines,
fit reasons, and unresolved eligibility questions.

See [the build roadmap](docs/roadmap.md) for completed setup work and the
remaining workflow and evaluation milestones.

Submission documentation:

- [Learning, observations, and challenges](docs/learning-log.md) — dated findings,
  fixes, reflections, and a submission/presentation evidence tracker.
- [Output examples](examples/README.md) — preserved actual runs and scenarios
  still to collect.
- [Evaluation plan and implemented benchmark](docs/evaluation.md) — what the
  frozen validation cases measure and what still needs model and user testing.

## Current milestone

The application implements **four agents**. The intake coordinator saves the
nonprofit's facts, the researcher retrieves grant evidence, and the analyst
compares the two. The evidence critic reviews the resulting eligibility checks.
It can accept the assessment with open questions or request corrections to
specific findings. The analyst gets up to two revision attempts. The coordinator then ranks up to three options for investigation.
Broader evaluation with independent profiles remains planned.

The analyst reports eight checks: applicant type, application route, SAM
registration, UEI readiness, grant type, cost sharing, deadline, and source
currentness. Each can be **met**, **not met**, or **needs verification**. Overall
outcomes remain **needs verification**, except an evidence-backed conflict with
the selected AmeriCorps grant type. No report claims confirmed eligibility.
Inactive registration, a missing UEI, or unresolved matching funds are readiness
issues rather than automatic exclusion from the whole opportunity.

The researcher remains a leaf agent with one retry for an empty terminal model
response. Missing or failed output produces an incomplete-research message;
it does not mean no matching grants exist. Python presents the profile, accepted
analyst report, and saved researcher findings without another coordinator model
rewrite. The [earlier handoff retest](examples/04-handoff-recovery-retest.md)
records the reliability milestone separately from the new analyst stage.

## What happens in the current prototype

1. A user describes a nonprofit project in local ADK Web.
2. The intake coordinator calls `save_nonprofit_profile`. Python validates and
   saves the profile in that ADK session.
3. If the organization type or project purpose is missing, research is blocked
   and the coordinator asks focused follow-up questions.
4. Once those two facts are present, the coordinator calls
   `opportunity_researcher` in a separate model turn. The researcher reads the
   validated profile from shared session state.
5. The researcher chooses queries and calls `search_grants` and
   `fetch_grant_details`. ADK executes these Python functions against Grants.gov.
6. After fetching an opportunity's details, it calls `read_grant_notice` in a
   separate step. The reader returns source-linked excerpts or an explicit
   source limitation. While notice attempts are pending, a before-model callback
   uses Gemini's native function-calling settings to request genuine notice
   calls. A draft that skips the required attempts is rejected as incomplete.
7. A callback checks that the researcher returned usable text. Empty or
   recognized error output leads to a fixed incomplete-research message.
8. After successful research with candidate records, an ADK dynamic node runs
   `eligibility_analyst`. Its typed input contains the current profile,
   normalized API facts, dated notice excerpts, and current attempt identifiers;
   the researcher's generated prose is not its source of facts.
9. Python validates the draft against that evidence registry, resolves source
   links and pages itself, and downgrades unsupported findings.
10. The coordinator runs `evidence_critic` with the same source records and the
    validated assessment. When a finding needs correction, the analyst receives
    the previous assessment and specific feedback. The application merges the
    requested changes, validates them, and asks the critic to review again.
11. Approval ends the loop. If two revisions leave a dispute, the final report
    marks the disputed checks as needing verification. A failed critic call
    leaves the assessment provisional. The coordinator displays the review
    outcome and eligibility checks, followed by the researcher's discovery notes.

In ADK Web, open **Traces** to see all four agents execute on a request with
a researched candidate. The initial static diagram shows the coordinator and
researcher. The coordinator starts the analyst and critic dynamically after research.
The application validates `AnalystInput` and serializes it in JSON mode before
the node call. The analyst uses `include_contents='none'` so earlier conversational
prose is not added alongside its explicit source-based input.

Only **organization type** and **project purpose** are required for initial
discovery. Service area, beneficiaries, requested funding, and timing can remain
unknown. Organization headquarters are recorded separately from the project's
service area: being a California nonprofit does not establish where its project
operates. The profile represents unknown facts as `null`, and the coordinator
is instructed to save only facts supplied by the user.

Six additional optional fields support the initial AmeriCorps checks: active
SAM registration, whether the organization has a valid UEI, planned submission
route, selected AmeriCorps grant type, whether it is a new AmeriCorps applicant,
and ability to meet matching requirements. These do not block initial discovery.
The application stores only a yes/no/unknown UEI readiness fact, not the actual
identifier. Unknown facts must remain unknown rather than becoming assumptions.

Corrections update only supplied fields. Explicit clearing removes a saved fact.
Invalid input preserves the previous valid profile, clears any saved research
summary, and blocks research until the affected field is corrected or cleared.
The profile belongs to the current session; a new session starts without it.

| File | Responsibility |
|---|---|
| [agent.py](grant_navigator/agent.py) | Defines the four agents, their model configuration, and workflow callbacks |
| [profile.py](grant_navigator/profile.py) | Defines typed profile fields, unknown-value handling, and discovery readiness |
| [intake.py](grant_navigator/tools/intake.py) | Saves session profiles, validates corrections, and gates research |
| [research.py](grant_navigator/research.py) | Clears stale research, records handoff outcomes, and handles absent or failed researcher output |
| [grants_gov.py](grant_navigator/tools/grants_gov.py) | Calls and normalizes public search/detail APIs |
| [notices.py](grant_navigator/tools/notices.py) | Loads reviewed PDF snapshots, checks their hashes, and returns page-linked excerpts |
| [notice_evidence.py](grant_navigator/notice_evidence.py) | Enforces detail-before-notice access and records actual evidence for the current research attempt |
| [opportunities.py](grant_navigator/opportunities.py) | Preserves typed API facts, their provenance, and the scope of general deadlines |
| [eligibility_workflow.py](grant_navigator/eligibility_workflow.py) | Builds source-based analyst input, runs the dynamic node, and accepts only current-attempt results |
| [eligibility.py](grant_navigator/eligibility.py) | Defines analyst draft/report contracts, citation checks, conservative rule guards, and rendering |
| [critic.py](grant_navigator/critic.py) | Validates critic coverage, resolves feedback against the current evidence, and marks unresolved disputes |
| [notice catalog](data/notices/catalog.json) | Binds each supported opportunity to its reviewed source, capture date, and checksum |
| [model_client.py](grant_navigator/model_client.py) | Buffers model turns for HTTP retries and retries one empty terminal model response |
| [run_web.py](scripts/run_web.py) | Starts the local demo with the selected model explicitly applied |
| [data/fixtures](data/fixtures/) and [data/notices](data/notices/) | Store dated source evidence for development |
| [tests](tests/) | Check tool contracts, intake, handoffs, model recovery, analyst evidence, and validation behavior |
| [evaluation cases](evaluation/analyst_cases.json) | Frozen developer-curated hypotheses for the analyst validation boundary |

The November 10 single-agent run made two searches and one detail call in
6.19 seconds. Its
[preserved output](examples/01-community-volunteer-search.md) records the actual
queries and generated answer. It is historical evidence of the model/tool
connection, not a result from the new two-agent workflow. Eligibility, ranking
quality, and usefulness to users still need evaluation.

The [November 12 intake/handoff example](examples/02-structured-intake-and-handoff.md)
preserves three actual Web API turns: missing details, live two-agent research,
and a profile correction without another search. Research completed in 8.04
seconds in that run. An earlier extraction mistake and the subsequent retest
are recorded alongside it. At that stage, **41 offline tests passed**, covering
tool contracts, transport recovery, profile rules, and ADK handoffs. Those
checks do not measure grant matching quality.

The [empty-result handoff example](examples/03-empty-result-handoff.md) preserves
a later failure: Grants.gov tools returned data, but an unexpected nested
transfer and an empty model response left the coordinator with `null`. Its
final answer incorrectly treated that as no matches. This is the evidence
behind the current handoff and empty-response safeguards, not a successful
retest of those safeguards.

After the reliability fixes, **79 offline tests passed**. A new live three-turn
check covered missing input, research, and a repeat search in the same session.
Both searches returned nonempty findings without transfers or error events,
and the final answers preserved the saved researcher text. Empty-response
recovery and deterministic failure reporting are covered by controlled tests;
the live retest establishes ordinary handoff behavior, not grant suitability.

Those 79 tests and examples describe the preceding reliability milestone.
The subsequent notice milestone passed **144 tests**, including notice-source contracts,
page citations, current-attempt evidence, native signed-call preservation,
and fail-closed workflow checks. The [full-notice example](examples/05-full-notice-evidence.md)
preserves the normal search, a cited AmeriCorps notice review, and an unavailable
notice result. The third live scenario succeeded after a quota cooldown;
the earlier signature and quota failures are retained as observations.

The analyst increment adds a separate [17-case frozen benchmark](docs/evaluation.md)
for evidence validation and conservative rule handling. It uses constructed
drafts and the saved PDF without calling Gemini. Its result measures the
validation boundary; it does not establish the analyst model's accuracy or
usefulness to users.

The November 13 analyst milestone passed **276 offline tests**, **17/17 frozen
validation cases**, and **two targeted live ADK scenarios**. The
[saved analyst example](examples/06-eligibility-analyst.md) includes unknown
facts followed by a profile correction and a conflict limited to the selected
grant type. It also preserves earlier schema failures. These are live smoke
checks of the implemented workflow, not a held-out model benchmark or user study.

## Local setup

Python 3.12 is selected in `.python-version`. From this directory:

```bash
uv sync
cp -n grant_navigator/.env.example grant_navigator/.env
```

The cryptography dependency is pinned to 48.0.1 because newer releases do not
publish an Intel macOS wheel for this computer. The project locks installed
versions in `uv.lock`.

Edit `grant_navigator/.env` and set your own `GOOGLE_API_KEY`. The key is needed
for Gemini/ADK conversations; the two Grants.gov API calls do not require one.
Keep `.env` local and out of Git.

Start the local ADK browser UI from this directory:

```bash
uv run python -m scripts.run_web
```

If an older server is running, stop it with Ctrl+C in its terminal before
running the command again. Open `http://localhost:8000`, select
`grant_navigator`, and choose **New Session** so the new workflow starts with
an empty profile. The Trace and State views can show the handoff and saved
profile. The implemented frozen benchmark runs from the terminal; it is not
automatically a dataset in the ADK Eval tab.

To check the code without model credentials:

```bash
uv run pytest
```

To refresh the dated example record from the live API:

```bash
uv run python -m scripts.snapshot_example
```

The script saves a normalized opportunity record under `data/fixtures/`.
The official state-hosted example notice is saved under `data/notices/`; check
that its text can be read with:

```bash
uv run python -m scripts.inspect_notice
```

## Try the intake and handoff

These are demo prompts and expected behaviors, not saved output examples.

1. In a new session: **“Find federal grants for our organization.”** The
   coordinator should ask for the organization type and proposed project;
   no Grants.gov research should start.
2. In a new session: **“We are a California 501(c)(3) nonprofit running
   community volunteer programs. Find posted federal grant opportunities worth
   investigating.”** This supplies the two required discovery facts. In the
   trace, inspect the profile save followed by the researcher call and its
   Grants.gov tools, then the eligibility analyst if candidates are fetched.
   Service area, beneficiaries, funding, timing, and registration facts should
   remain unknown unless supplied.
3. In that same session: **“Our project serves seniors in Santa Clara County,
   and we are seeking $75,000. Update the search using those details.”** The
   saved profile should retain earlier facts, add the correction, and replace
   the old research summary when new research completes.

Research is gated by Python callbacks as well as model instructions. The
coordinator must save or validate the profile in the current invocation before
delegating. A model response that attempts a profile save and research in the
same tool batch is blocked from starting research, regardless of call order.
The researcher and its tools also check readiness. These checks validate the
profile's structure and required fields; they do not prove grant eligibility
or that the model extracted every user fact correctly.

## Try full-notice evidence

In a new session, use a request that names the opportunity with a reviewed PDF:

> We are a California 501(c)(3) nonprofit running community volunteer programs.
> Investigate AmeriCorps opportunity 363696. Read the full notice and cite the
> pages supporting the general deadline, single-state application route, and
> cost-sharing rules. Keep our project service area unknown unless I provide it.

The expected sequence is `save_nonprofit_profile -> opportunity_researcher ->
fetch_grant_details -> read_grant_notice -> eligibility_analyst -> final answer`;
the researcher may
also search Grants.gov. In Events/Traces, inspect the notice tool's actual
excerpts. In State, `research_evidence` binds fetched details and notice results
to the current invocation and profile version. The final response includes a
source-access summary and accepted analyst checks; retrieving excerpts does not
mean every rule was reviewed.

The original community-volunteer prompt still works. It may identify other
opportunities whose PDFs are not yet in the catalog, so the notice reader will
report that evidence is unavailable rather than inventing a notice or a rule.

The initial [catalog](data/notices/catalog.json) contains one reviewed notice:
AmeriCorps opportunity `363696`, number `AC-08-28-26`. It prefers the saved
November 10, 2026 snapshot, verifies its SHA256 hash, and returns lexical matches
with evidence IDs and links such as `#page=8`. Page numbers are **1-based physical
PDF pages**, including cover pages; printed page labels can differ in other PDFs.

If the saved file is missing, the reader can download the same approved HTTPS
`.gov` PDF, subject to a 15-second timeout and a 10 MiB limit. The downloaded
bytes must match the catalog hash. It does not accept model-supplied URLs or
automatically discover PDFs from agency webpages. Redirected, changed, malformed,
encrypted, or unreadable sources receive explicit statuses. Scanned PDFs without
extractable text need OCR, which is not implemented.

Notice access is nonfatal to discovery. An unavailable source, changed checksum,
or query with no excerpts leaves rules unresolved. Every result keeps
`currentness_verified=false` and `eligibility_status="not_assessed"`: a dated
snapshot is not proof that amendments, the applicable deadline, or eligibility
have been verified. Adding more reviewed notices is necessary for broader coverage.

Python enforces a notice attempt for each successfully fetched candidate before
accepting the researcher's final draft. While reads are pending, a before-model
callback sets function-calling mode `ANY` with only `read_grant_notice` allowed
and supplies the pending opportunity IDs. The provider creates the actual call;
the application preserves its original `Part`, including its thought signature.
After pending attempts complete, normal `AUTO` behavior resumes. Genuine
required-read calls are marked with `custom_metadata.notice_read_enforced`.

A notice read requested in the same batch as a detail fetch is blocked to keep
source identity checks ordered. There are at most six notice-required model
rounds per research attempt. If the model still ends without the required reads,
or that limit is reached, `NOTICE_REVIEW_INCOMPLETE` leads to the fixed incomplete-
research message. The application does not manufacture function-call history.
This enforces source access; it does not validate the model's interpretation of
the passages. The analyst and critic then review how the rules apply to the saved profile.

During the live check, this project/model reported a free-tier limit of 15
generation requests per minute. A single user request can make several model
calls. Space consecutive demo scenarios and check the actual quota response;
the application does not automatically replay a quota-limited workflow.

When testing the corrected native-call implementation, restart the updated
server and choose **New Session**. Refreshing an older failed conversation does
not remove its unsigned function-call history, which Gemini can continue to reject.

## Try the eligibility analyst and critic

These are proposed demo scenarios, not claims that a new live run has passed.
Use the targeted AmeriCorps request above to keep the first scenario within the
reviewed notice catalog. The original community-volunteer request is also valid,
but discovery may return uncataloged opportunities.

1. **Unknown information:** Supply only the California nonprofit and community
   volunteer facts. Inspect the analyst's eight checks and follow-up questions.
   A California headquarters does not establish a single-state project, and
   missing SAM/UEI or grant-type facts should stay unresolved. A general API
   deadline must not be presented as the user's confirmed submission deadline.
2. **Selected-option conflict:** In the same session, send: **“We are a new
   AmeriCorps applicant and want a full-cost fixed-amount grant. Our SAM
   registration is active and we have a valid UEI. Investigate opportunity
   363696 again using these facts.”** With the supporting page 8 exclusion
   excerpt, the accepted report should flag that selected grant type as a
   blocking issue. It must not reject every grant type under the notice or
   imply the organization cannot pursue another eligible mechanism.

In State, compare `eligibility_raw` with `eligibility_analysis` and inspect
`eligibility_outcome` and `eligibility_input_scope`. Raw model JSON is a draft,
not the accepted result. The report is tied to the current invocation and profile
version. Python checks evidence identity and quote membership and supplies the
links; correct citation mechanics alone do not prove correct interpretation.
An unavailable notice leaves all rule checks unresolved and asks for the
official source first.

In **Traces**, follow `eligibility_analyst` and then `evidence_critic`. A second
analyst span in the same review indicates a revision. In **State**, inspect
`critic_outcome` for the result and revision count. Each entry in `critic_history`
records the assessment, the critic's original response, and the feedback
accepted by the application. Compare successive assessments to see what changed.
Approval covers the eligibility checks against the supplied evidence. The
researcher's discovery notes have their own label in the final response.

In the verified live run all four agents executed, the workflow requested one
revision, and the second review accepted the assessment. The saved example
also includes a separate controlled run in which the critic identifies a
missed registration clause. [Critic demo and recorded outputs](examples/07-critic-review.md)

Run the offline validation benchmark from the project root:

```bash
uv run python -m scripts.evaluate_analyst
```

See [evaluation scope and metrics](docs/evaluation.md) for the frozen inputs,
reviewable JSON output, deliberate-error cases, and remaining model/user studies.

## Gemini temporarily unavailable

A `503 UNAVAILABLE` response with a high-demand message comes from Gemini's
model service. The prototype defaults to `gemini-3.5-flash-lite`, which supports
the function calls used by our Grants.gov tools. The moving `gemini-flash-latest`
alias returned 503/504 errors during the initial local test.

Use the project launcher shown above: it prints the chosen model and explicitly
applies the model from `grant_navigator/.env`. A long-running ADK process or an
exported shell variable can otherwise keep an old model active. To override the
local setting for a run, use `uv run python -m scripts.run_web --model MODEL_ID`.

The model client uses a 20-second HTTP timeout per attempt and at most
three HTTP attempts per generation request, with short exponential delays for
transient server failures.
Authentication and quota errors are surfaced without repeated attempts.
Retries can recover a brief outage but cannot restore an overloaded service.
Each model response is buffered so the same retry policy applies when the
browser requests streaming. Tool events and agent traces remain available;
model text appears when that model turn finishes.

A separate content check retries the same model request once if Gemini ends
with `STOP` but provides no usable content or tool call. That retry does not
replay tools or restart the workflow. If the second response is also empty,
ADK can still surface the error. This extra retry excludes error responses,
safety blocks, refusals, and other finish reasons; the transient HTTP retry
policy above remains separate. Each of the two generation requests can make
up to three HTTP attempts, so the combined upper bound is six HTTP attempts
for that model turn. An extra generation request can add latency and token
usage; the application logs when it uses this recovery path.

After changing model settings or `grant_navigator/.env`, restart ADK Web with
Ctrl+C and `uv run python -m scripts.run_web`, then use a new session. Send `Hello`
first to check the model connection before testing a Grants.gov search.

## How the shortlist is ranked

The analyst compares the nonprofit profile with each fetched grant synopsis. For
each fit claim it returns the relevant wording. Python checks that the quote
occurs in that opportunity's description and that the profile supplies the
corresponding fact. Project-purpose fit earns 40 points, beneficiaries 15,
service area 10, project timing 15, and a request within both published award
bounds 20. Unknowns earn no points and appear next to the result. A general
application date does not establish a project's start period.

The shortlist requires evidence of purpose fit. It sets aside closed, archived
or forecasted listings, past general dates needing verification, and a reviewed
conflict with the chosen grant option. Among the remaining options, grants
without an identified fit conflict come first, then higher points, then
ascending ID for repeatable ties. The points measure documented fit for further
investigation. A high score can coexist with unresolved eligibility requirements.
The critic reviews eligibility. The relevance of a correctly quoted synopsis
still depends on the analyst's interpretation.

In ADK Web, start a new session, describe the people, place, amount and timing
of your project, and ask for up to three posted opportunities. In the final
answer look for **Grants to investigate first**. Open **State → grant_shortlist**
for scores, evidence, unknowns and options set aside. A search may return fewer
than three candidates.

Run the repeatable classroom comparison from the project root with
`uv run pytest -q tests/test_ranking.py`. [Expected order and sample output](examples/08-ranked-shortlist.md).

## Data and source limits

The public Grants.gov `search2` and `fetchOpportunity` endpoints expose search
results and synopses. A synopsis may omit restrictions in the full Notice of
Funding Opportunity (NOFO), and the detail API may expose attachment metadata
without a direct document-download URL. We have started curating full notices
for the initial evaluation set and keep an as-of date for every source. Never
present an API summary alone as a definitive eligibility decision.

The first saved example is AmeriCorps opportunity `AC-08-28-26`. Its API record
links to the AmeriCorps funding page; the local full notice was downloaded from
an [official Oregon government mirror](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf).
The snapshot records the notice checksum, so the reader can detect changed
bytes. The notice itself may have applicant routes and deadlines that are more
specific than the API summary. The saved document is an Initial Announcement;
current amendments are not automatically checked.

Grants.gov API documentation: <https://www.grants.gov/api/api-guide>

Required API attribution: **This product uses the Grants.gov API but is not
endorsed or certified by the U.S. Department of Health and Human Services.**
