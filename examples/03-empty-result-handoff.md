# Example 03: Empty-result handoff failure

Status: observed user run on November 12, 2026, before the latest reliability
fix. This is a failure example, not a successful retest.

Invocation: `e-52f3501f-0c4f-43db-a50d-c9e700a4b502`.

Selected evidence: [public demonstration events](03-empty-result-handoff.json).
The export preserves the prompt, tool arguments, selected result summaries,
error, and generated texts. It omits session state, credentials, and private
configuration. Text in the JSON is preserved as generated.

## Input

```text
We are a California 501(c)(3) nonprofit running community volunteer programs. Find posted federal grant opportunities worth investigating.
```

## Observed sequence

| Step | Agent or tool | Observed result |
|---|---|---|
| 1 | Coordinator → `save_nonprofit_profile` | Saved organization type, location, and project purpose; profile ready for discovery |
| 2 | Coordinator → `opportunity_researcher` | Delegated the request |
| 3 | Researcher → `search_grants` | Three successful calls; each returned three records |
| 4 | Researcher → `fetch_grant_details` | Successfully retrieved IDs 363771, 362715, and 362062 |
| 5 | Researcher → `transfer_to_agent` | Requested transfer to `grant_navigator` inside the research branch |
| 6 | Nested coordinator | Produced candidate descriptions, then called `save_nonprofit_profile` with `{}` |
| 7 | Nested coordinator | Error: `MODEL_RETURNED_NO_CONTENT`, empty `STOP` response |
| 8 | Outer researcher handoff | Returned `{"result": null}` |
| 9 | Final coordinator | Reported no matching grant opportunities, without a completed research result supporting that conclusion |

The actual searches were:

| Keyword | Requested rows | Total reported | Records returned |
|---|---|---|---|
| `community volunteer programs` | 3 | 693 | 3 |
| `volunteer programs` | 3 | 680 | 3 |
| `volunteer service community program` | 3 | 709 | 3 |

These are keyword-result counts from this run, not counts of eligible grants.
The retrieved records do not establish that the user's project was a good fit.

## Observed error and handoff

```text
MODEL_RETURNED_NO_CONTENT
The model returned no content (finish_reason=STOP with empty parts).
```

```json
{"result": null}
```

The nested coordinator had already described three candidates: Inspire Grants
for Small Museums (2027), the Outdoor Recreation Legacy Partnership Program,
and Engineering Biological and Biomedical Systems. This material appeared
inside the nested branch; the outer call still returned `null`. The complete
nested text is in the selected JSON, so the final answer can be compared with
what happened earlier in the trace.

The final coordinator's grant section said, verbatim:

```text
### Grant Opportunities
*(No matching grant opportunities were returned from the search at this time.)*
```

The complete final answer is preserved in the JSON. A missing agent result did
not justify this conclusion. Nor would returning those keyword hits alone
justify recommending them as suitable grants.

## Changes prompted by this observation

- Disabled research-agent transfers to its parent and peers. The researcher's
  own final answer is returned to the coordinator automatically.
- Added one retry of the same model request for an empty terminal `STOP`,
  without replaying the tools. Errors, safety blocks, refusals, and other finish
  reasons do not trigger this additional content retry.
- Added a handoff guard for raw `None`, blank/null-like findings, and recognized
  errors. These produce a fixed incomplete-research explanation, rather than a
  generated no-match conclusion. The previous summary is cleared when a new
  attempt starts and when a handoff fails.

The fixed incomplete-research message is defined in
[research.py](../grant_navigator/research.py):

```text
I could not complete grant research in this run. Your nonprofit profile is saved, but the research step did not return usable findings. This run does not establish whether matching grants are available. Please try the search again.
```

That message is the implemented failure behavior; it is not presented here as
an actual output from a live post-fix run.

## What this example establishes

The trace establishes successful external API calls, an unexpected nested
transfer, a later empty model response, a missing researcher result, and an
unsupported final conclusion. The transfer preceded the empty response; this
does not prove that it caused the model provider to return empty content.

The reliability changes address control flow, recovery from one empty
response, and failure reporting. They do not establish source correctness,
grant relevance, eligibility, or ranking quality. New regression and live
verification results must be assessed separately from this failure record.

Related documentation: [learning log](../docs/learning-log.md) and
[roadmap](../docs/roadmap.md).
