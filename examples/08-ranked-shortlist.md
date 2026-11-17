# Which tutoring grant should the nonprofit investigate first?

This classroom scenario uses fictional grant descriptions. The nonprofit requests
$50,000 for after-school tutoring for middle school students in Alameda County
starting in fall 2027. We recorded the [expected order and reasons](../evaluation/ranking_case.json)
before implementing the score.

| Expected and observed position | Opportunity | Fit points | Reason for placement |
|---|---|---:|---|
| 1 | Alameda After-School Partnerships | 100 | Activity, students, county, start period and requested amount all fit. |
| 2 | Regional Learning Grants | 75 | Activity, students and budget fit. Verify geography and timing. |
| 3 | Community Learning Microgrants | 40 | Activity fits. The $10,000 ceiling is below the $50,000 request. Audience, geography and timing are open. |

The controlled ADK run exercised the coordinator, researcher, analyst, critic
and final report using scripted model messages. It also checked that a quotation
copied from a different grant cannot establish purpose fit, and that a conflict
with a selected grant type keeps that option off the shortlist. The test uses
fictional IDs, and those IDs should not be entered in a live Grants.gov search.

From the project directory, run `uv run pytest -q tests/test_ranking.py`.
This design example demonstrates the ordering rule. Estimating how often the
navigator chooses a useful first grant requires independently labeled profiles
and grants, including cases where no candidate deserves a recommendation.

A separate live check passed the same three frozen descriptions to Gemini.
The first attempt exceeded the optional summary length. After removing unused
summary fields, a second run omitted fit evidence for every option and the
ranker set all three aside. We made the fit field explicit in the model schema
and clarified that synopsis evidence can support investigation even with
eligibility unresolved. The next live analyst call produced 100, 75 and 40
points in the expected order. That check exercised live extraction and the
ranking function. The four-agent check above used scripted model messages.
[Recorded live evidence and scores](08-ranked-shortlist.json)
