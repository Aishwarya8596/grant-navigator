# Example 07 — Critic review

[Recorded outputs and review rounds](07-critic-review.json)

## Live ADK Web run

On 2026-11-13 the local application received the following synthetic nonprofit request.

> We are a California 501(c)(3) nonprofit running community volunteer programs. We are a new AmeriCorps applicant considering a full-cost fixed-amount grant. Our SAM registration is active and we have a valid UEI. Investigate AmeriCorps opportunity 363696 (AC-08-28-26). Read the grant notice and explain which requirements we meet, which we need to verify, and whether any issue affects our chosen grant type or the entire opportunity.

Model `gemini-3.5-flash-lite`, ADK 2.14.0. This request took 23.5 seconds.

The recorded agent sequence was `grant_navigator` → `opportunity_researcher` → `grant_navigator` → `eligibility_analyst` → `evidence_critic` → `eligibility_analyst` → `evidence_critic` → `grant_navigator`.

The critic ended with `approved` after 1 analyst revision(s).

On the first pass the critic model proposed approval. Python detected two
unsupported references, one for cost sharing and one for the applicable
deadline, and requested corrections. The analyst added accepted references on
pages 7 and 1 respectively. Both findings still needed verification. The second
critic response and the source checks agreed on approval. The round table shows
the decision the application used. The JSON records the model response and the
origin of each correction.

| Round | Critic decision | Rules flagged |
|---|---|---|
| 1 | revise | cost_sharing, deadline |
| 2 | approve | None |

The final assessment recorded **blocking issue** for opportunity 363696. The grant type check was **not met**. The project service area, submission route, and applicant-specific deadline remained unresolved.

The JSON includes the original prompt, tool arguments, saved notice excerpts, review history, and final user-facing response.

The first live attempt returned an approval with an empty candidate review list. The application recorded an incomplete review. The JSON preserves the draft and outcome from that attempt.

## Controlled correction

The integration scenario uses the ADK Runner, scripted model responses, a mocked Grants.gov response, and the saved AmeriCorps PDF. The profile states that SAM registration is active.

1. The first assessment marked SAM registration **needs verification**.
2. The critic requested a targeted change. Its recorded feedback follows.

> Compare the stated active SAM registration with the mandatory registration clause on page 8 and cite the clause.

3. The revised assessment marked SAM registration **met** and cited notice page 8.
4. The critic approved the revised assessment at the second review.

The example records a repeatable correction of one requirement using prescribed agent responses. The source snapshot and the remaining unresolved requirements bound the finding.

The [integration scenario](../tests/test_critic_workflow.py) exercises this correction through the same workflow callbacks that ADK Web runs.
