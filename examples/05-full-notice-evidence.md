# Example 05: Full-notice evidence with page citations

Live session started: 2026-11-13T00:51:47.585649-08:00 (America/Los_Angeles).

Model: `gemini-3.5-flash-lite`, temperature 0. These are actual requests through the local
ADK Web `/run_sse` endpoint, with real Grants.gov calls and public demonstration
profiles. Model text is buffered; ADK still streams agent and tool events.

Selected evidence: [successful scenarios](05-full-notice-evidence.json).

## Implemented behavior

The two-agent workflow now uses `read_grant_notice` after candidate detail retrieval.
The researcher requests the read through Gemini's native function-calling mode.
The tool returns page-linked passages from a checksum-verified cataloged notice,
or an explicit source limitation. A source-access block is added by Python before
the saved researcher findings. No final model rewrite can remove those findings.

Only the AmeriCorps notice is in the initial reviewed catalog. This is selected
evidence from a dated snapshot, not a current or exhaustive eligibility review.
Candidate fit, eligibility decisions, ranking, and critic review remain planned.

## Reviewed-source download check

The approved Oregon government PDF source was downloaded through the bounded
retrieval path without moving or changing the original saved PDF. Its 304,842
bytes matched the reviewed SHA256 checksum. The cached download was reused
during the final retest. The agent itself read the existing November 10 snapshot;
retrieving the same bytes does not establish that no amendment exists.

```json
{
  "status": "verified",
  "retrieval_mode": "downloaded_verified_snapshot",
  "bytes": 304842,
  "sha256": "250b6fff76658a2633955d9cf945ba91da58226c9e939e4182f5e125af3898b6",
  "retrieved_at_utc": "2026-11-13T08:36:20.548444+00:00",
  "source_url": "https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf"
}
```

## 1. Original discovery prompt

**Input**

> We are a California 501(c)(3) nonprofit running community volunteer programs. Find posted federal grant opportunities worth investigating.

Observed elapsed time: 13.47 seconds.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{"organization_location": "California", "organization_type": "501(c)(3) nonprofit", "project_purpose": "Community volunteer programs"}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Find federal grant opportunities for a California 501(c)(3) nonprofit running community volunteer programs."}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "community volunteer programs", "rows": 3}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "volunteer programs", "rows": 3}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "volunteer community service", "rows": 3}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363771}`.
- `opportunity_researcher` called `read_grant_notice` with `{"focus": "deadlines applicant routes eligibility cost sharing state commission", "max_excerpts": 8, "opportunity_id": 363771}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 362715}`.
- `opportunity_researcher` called `read_grant_notice` with `{"focus": "deadlines eligibility application route cost sharing state commission matching requirement", "max_excerpts": 8, "opportunity_id": 362715}`.

Native required-notice calls were marked in event metadata:
`[[363771], [362715]]`.

**Final coordinator output (verbatim)**

**Nonprofit profile**

- **Organization type:** 501(c)(3) nonprofit
- **Organization location:** California
- **Project purpose:** Community volunteer programs
- **Service area:** Unknown
- **Beneficiaries:** Unknown
- **Requested funding:** Unknown
- **Project timing:** Unknown

---

**Notice sources retrieved**

- **IGSM-FY27:** Full-notice evidence unavailable (notice unavailable); synopsis-only discovery.
- **P26AS00125:** Full-notice evidence unavailable (notice unavailable); synopsis-only discovery.

These are selected excerpts. Current amendments, applicant-specific deadlines, and eligibility remain unverified.

---

Based on your search for federal grant opportunities supporting community volunteer programs for a 501(c)(3) nonprofit located in California, the following candidates are worth investigating. 

Note: The saved profile indicates that the **service area is unknown** (headquarters are in California, but specific project service areas have not been provided). Additionally, funding amounts, beneficiaries, and project timing are unspecified.

---

### Candidate Worth Investigating 1
* **ID:** 363771
* **Number:** IGSM-FY27
* **Title:** Inspire Grants for Small Museums (2027)
* **Agency:** Institute of Museum and Library Services
* **API Deadline:** November 13, 2026 (Source: Grants.gov API synopsis)
* **Synopsis-Based Reason to Investigate:** This program supports project-based efforts to serve the public through educational programs, exhibits, and **community partnerships**. If your nonprofit operates community volunteer programs within or in partnership with a small museum, this grant could help build organizational capacity and public engagement.
* **Source Link:** [Grants.gov Opportunity 363771](https://www.grants.gov/search-results-detail/363771)
* **Unresolved Rules & Missing Facts:** The reviewed full-notice PDF was unavailable via automated tools, so eligibility criteria for specific nonprofit types (beyond small museums) and cost-sharing requirements must be verified directly from the official agency announcement.

---

### Candidate Worth Investigating 2
* **ID:** 362715
* **Number:** P26AS00125
* **Title:** Outdoor Recreation Legacy Partnership Program (ORLP) Recurring Notice 5 Year
* **Agency:** Department of the Interior / National Park Service
* **API Deadline:** November 01, 2030 (Source: Grants.gov API synopsis)
* **Synopsis-Based Reason to Investigate:** If your community volunteer programs involve outdoor recreation, park development, or environmental stewardship in qualifying urban areas (population of 25,000 or more), this program provides substantial funding to acquire land and water or develop/renovate outdoor recreation facilities.
* **Source Link:** [Grants.gov Opportunity 362715](https://www.grants.gov/search-results-detail/362715)
* **Unresolved Rules & Missing Facts:** This program generally requires state government or tribal sponsorship and carries a mandatory 1:1 (50%) non-federal matching requirement, as well as property protection rules in perpetuity. The exact application route for nonprofits and local single-state rules depend on your specific project service area. The reviewed full-notice PDF was unavailable via automated tools, so you should review the attached synopsis documents directly on Grants.gov.

---

### Unknown Profile Details Affecting Matching
* **Service Area:** Because the specific service area within California is unknown, single-state rules, local urban population thresholds (for ORLP), and regional eligibility cannot be definitively assessed.
* **Beneficiaries & Project Scope:** Without details on whether your volunteer programs focus on museums, parks, youth, or social services, alignment with specific agency priorities remains preliminary.

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## 2. Targeted AmeriCorps notice review

**Input**

> Using my saved profile, investigate AmeriCorps opportunity 363696 (AC-08-28-26). Read the full notice and cite pages for deadlines, the application route, and cost-sharing rules. Do not assume where our project operates.

Observed elapsed time: 8.95 seconds.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Investigate AmeriCorps opportunity 363696 (AC-08-28-26), read the full notice, and cite pages for deadlines, application route, and cost-sharing rules."}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363696}`.
- `opportunity_researcher` called `read_grant_notice` with `{"focus": "deadlines application route eligibility state commission cost sharing matching rules", "max_excerpts": 8, "opportunity_id": 363696}`.

Native required-notice calls were marked in event metadata:
`[[363696]]`.

**Final coordinator output (verbatim)**

**Nonprofit profile**

- **Organization type:** 501(c)(3) nonprofit
- **Organization location:** California
- **Project purpose:** Community volunteer programs
- **Service area:** Unknown
- **Beneficiaries:** Unknown
- **Requested funding:** Unknown
- **Project timing:** Unknown

---

**Notice sources retrieved**

- **AC-08-28-26:** Notice excerpts retrieved ([p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1), [p. 6](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=6), [p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7), [p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8), [p. 9](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=9), [p. 23](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=23)); saved snapshot, captured 2026-11-10.

These are selected excerpts. Current amendments, applicant-specific deadlines, and eligibility remain unverified.

---

### Candidate Worth Investigating

* **ID:** 363696
* **Opportunity Number:** AC-08-28-26
* **Title:** Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants
* **Agency:** AmeriCorps
* **API Deadline:** January 13, 2027 (Note: The API deadline is listed as January 13, 2027; however, the notice states that single-state applicants must contact their state service commission as early as possible because commissions may set their deadlines well in advance of the federal deadline [Notice p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1)).
* **Synopsis-Based Reason to Investigate:** The organization's project purpose aligns with engaging community volunteers, and 501(c)(3) nonprofits are explicitly eligible applicant types to operate AmeriCorps programs addressing community challenges through national service [Notice p. 1, 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1).
* **Source Link:** [Grants.gov Opportunity 363696](https://www.grants.gov/search-results-detail/363696)

---

### Notice Rules & Requirements (Dated Snapshot)

* **Deadlines:** Applications are due no later than Wednesday, January 13, 2027, by 5:00 p.m. Eastern Time [Notice p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1). Single-state applicants must contact their state service commission early, as state commissions can set earlier deadlines [Notice p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1).
* **Application Route:** Organizations planning to operate in only one state must apply through their state or territory service commission using a state-based selection process [Notice p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8). Multi-state (National Direct) applicants apply directly to AmeriCorps [Notice p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8).
* **Cost-Sharing and Matching Rules:** Cost-reimbursement grants require non-AmeriCorps cash and/or in-kind matching contributions [Notice p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7). First-time successful applicants must match at 24 percent for the first three-year funding period, increasing incrementally to 30 percent by year ten [Notice p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7). Fixed amount grants carry no cost-sharing or matching requirements [Notice p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7).

---

### Unresolved Rules and Missing Facts

* **Service Area:** The saved nonprofit profile does not specify a service area (listed as `null`), so it is unknown whether the applicant operates in a single state or multiple states. This determines whether the organization must apply through a state service commission or directly to AmeriCorps as a National Direct applicant.
* **Funding Amount & Project Timing:** Specific funding amounts and project timing details are not provided in the saved profile, meaning budget size and grant type fit (cost reimbursement vs. fixed amount) remain unverified.

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## 3. Uncataloged notice after quota cooldown

**Input**

> Using the same profile, investigate Grants.gov opportunity 363771. Try to read its full notice. If a reviewed notice is unavailable, explain that limitation and do not determine eligibility.

Observed elapsed time: 8.15 seconds.

**Actual tool sequence**

- `grant_navigator` called `opportunity_researcher` with `{"request": "Investigate Grants.gov opportunity 363771 and try to read its full notice."}`.
- `grant_navigator` called `save_nonprofit_profile` with `{}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Investigate Grants.gov opportunity 363771 and try to read its full notice."}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363771}`.
- `opportunity_researcher` called `read_grant_notice` with `{"focus": "deadlines application route eligibility cost sharing state commission deadlines application route eligibility cost sharing state commission", "max_excerpts": 8, "opportunity_id": 363771}`.

Native required-notice calls were marked in event metadata:
`[[363771]]`.

**Final coordinator output (verbatim)**

**Nonprofit profile**

- **Organization type:** 501(c)(3) nonprofit
- **Organization location:** California
- **Project purpose:** Community volunteer programs
- **Service area:** Unknown
- **Beneficiaries:** Unknown
- **Requested funding:** Unknown
- **Project timing:** Unknown

---

**Notice sources retrieved**

- **IGSM-FY27:** Full-notice evidence unavailable (notice unavailable); synopsis-only discovery.

These are selected excerpts. Current amendments, applicant-specific deadlines, and eligibility remain unverified.

---

### Candidate Worth Investigating

**Opportunity ID:** 363771  
**Opportunity Number:** IGSM-FY27  
**Title:** Inspire Grants for Small Museums (2027)  
**Agency:** Not provided via API synopsis  
**API Deadline:** Not provided  
**Synopsis-Based Reason to Investigate:** This opportunity supports project-based efforts such as community partnerships, educational programs, and exhibits. Although the saved nonprofit profile focuses on community volunteer programs, this grant specifically targets museum services and capacity building for small museums. However, the nonprofit's project purpose could potentially align if structured around museum volunteer or community engagement programs, making it worth investigating if the organization qualifies as a small museum.  
**Source Link:** [https://www.grants.gov/search-results-detail/363771](https://www.grants.gov/search-results-detail/363771)

---

### Research Findings and Unresolved Questions

* **Service Area:** The saved nonprofit profile does not specify a service area (`service_area=null`), so it is unknown. Single-state rules or geographic restrictions would depend on the project service area rather than the headquarters location.
* **Applicant Eligibility:** The API applicant types list "Others," and the synopsis indicates the program is designed for small museums of all disciplines (including rural, remote, or previously unfunded institutions). It remains unverified whether a general 501(c)(3) nonprofit whose purpose is community volunteer programs meets the definition of an eligible museum.
* **Deadlines:** The API does not provide a specific deadline date for this opportunity.
* **Cost Sharing / Matching:** The API indicates that cost sharing is required (`cost_sharing: true`), but the exact percentage or waiver rules remain unverified from the synopsis alone.
* **Notice Status:** The full-notice PDF snapshot was unavailable through the automated notice reader tool (`notice_unavailable`). Therefore, specific notice rules, application routes, and detailed eligibility criteria could not be reviewed from source excerpts.

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## Earlier observations and corrections

### Provider signature requirement

The [first live attempt](05-notice-signature-observation.json) failed with a
400 `INVALID_ARGUMENT`: a workflow-inserted function-call part lacked the
Gemini thought signature. The PDF download and reader had worked. Offline
scripted models did not enforce the provider's signature protocol.

We removed manufactured model calls. The before-model callback now constrains
Gemini to generate a real `read_grant_notice` call while a notice is pending.
Original signed model parts remain intact. When the source attempts finish,
ordinary answering resumes. A premature final answer fails explicitly rather
than inventing document access. The required-notice phase has a six-model-turn limit.

### Per-minute quota

The [first native-tool run](05-notice-quota-observation.json) completed scenarios
1 and 2, but the third request hit a 429 quota error: this project/model was
limited to 15 free-tier generation requests per minute at that time. After
the reported cooldown elapsed, only the third scenario was retried. It
completed successfully in 8.15 seconds. This was a test-level retry after
waiting; the application did not automatically replay a quota-limited workflow.

The successful JSON combines the original first two scenarios with that
later retry. Both unsuccessful observations remain preserved separately.

## Review notes and remaining evaluation

- Scenario 1 exercised the usual discovery prompt and explicit unavailable-notice
  results for uncataloged opportunities.
- Scenario 2 retrieved the 28-page AmeriCorps snapshot and cited actual pages.
  The profile service area stayed unknown; applicant routes and cost-sharing
  conditions were reported conditionally rather than applied as a final decision.
- Scenario 3 retained only the new opportunity's evidence and reported synopsis-only
  discovery. An initial delegation before profile validation was blocked; the
  coordinator then saved/validated the profile and completed the handoff.
- Source access and text delivery are checked. Generated claim support still
  needs analyst/critic evaluation. For example, a combined citation label
  “Notice p. 1, 8” uses only a page-1 URL, and raw field names still appeared
  in some prose despite the plain-language instruction.
- Timings are individual observations, not performance benchmarks. A user
  request can require several model calls, so rapid consecutive demos can
  reach a per-minute quota before the individual prompts seem numerous.
