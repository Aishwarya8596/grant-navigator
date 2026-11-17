# Example 04: Research handoff after the reliability fix

Observed: 2026-11-12T15:27:07.428769-08:00 (America/Los_Angeles).

Model: `gemini-3.5-flash-lite`, temperature 0, local ADK Web `/run_sse`
with streaming requested and live Grants.gov calls. These are public
demonstration profiles; only selected prompts, responses, tool arguments,
and state fields are preserved.

Selected evidence: [three-turn session](04-handoff-recovery-retest.json).
The original failure is preserved in [Example 03](03-empty-result-handoff.md).

## Checks and result

- Missing essentials produced questions without grant API calls.
- Both research requests returned nonempty findings through the researcher tool.
- No transfer call or error event appeared in these runs.
- A repeated search validated the saved profile and made fresh external calls.
- Both successful turns recorded `research_outcome.status="completed"`.
- Service area remained unknown because only the organization location was supplied.
- Each final coordinator answer appended the saved researcher findings unchanged,
  including their source links and deadline caveats. Surrounding whitespace is normalized
  when the handoff result is saved; the coordinator performs no final model rewrite.

The server logged 0 empty-response retries during this check. Recovery from
an empty response and the fixed failure message are tested with controlled offline
cases, including failure after successful grant API calls. The complete offline
suite passed 79 tests. These tests do not establish grant relevance, eligibility
accuracy, or citation support.

## 1. Missing required details

**Input**

> Find federal grants for our organization.

Observed elapsed time: 15.67 seconds.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{}`.

**Final coordinator answer (verbatim)**

Welcome to the federal grant navigator! I'd be happy to help you find federal grants for your organization. 

To get started, could you please tell me a little more about your work? Specifically:
1. What type of organization is applying (for example, a 501(c)(3) nonprofit, local government agency, or tribal organization)?
2. What specific activities or project would the grant fund? 

*(Optional details like your organization's location, the geographic area your project serves, who benefits from your program, and your funding amount or timeline are also helpful if you'd like to share them!)*

## 2. Research with minimum profile

**Input**

> We are a California 501(c)(3) nonprofit running community volunteer programs. Find posted federal grant opportunities worth investigating.

Observed elapsed time: 38.89 seconds.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{"organization_location": "California", "organization_type": "501(c)(3) nonprofit", "project_purpose": "Community volunteer programs"}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Federal grants for a California 501(c)(3) nonprofit running community volunteer programs"}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "community volunteer programs", "rows": 3}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "volunteer service community engagement", "rows": 3}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "AmeriCorps volunteer service community programs", "rows": 3}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363696}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 358864}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 362062}`.

**Final coordinator answer (verbatim)**

**Nonprofit profile**

- **Organization type:** 501(c)(3) nonprofit
- **Organization location:** California
- **Project purpose:** Community volunteer programs
- **Service area:** Unknown
- **Beneficiaries:** Unknown
- **Requested funding:** Unknown
- **Project timing:** Unknown

---

Based on the profile provided—a 501(c)(3) nonprofit located in California running community volunteer programs—federal grant discovery requires looking for funding opportunities centered on civic engagement, national service, community partnerships, and volunteer mobilization. 

**Unknown profile details that could affect matching:**
* **Service area:** The nonprofit's specific service area within California (e.g., statewide, specific counties or cities) is unknown. Grant eligibility and local fit often depend on targeted geographic boundaries.
* **Specific focus/beneficiaries of volunteer programs:** The specific demographic or issue area addressed by the volunteer programs (e.g., youth development, environmental conservation, senior services, disaster response) is not specified.
* **Funding amount required and project timing:** Neither the target budget size nor the timeline for the project is provided.

Below are three federal grant opportunities worth investigating based on activities related to community engagement, volunteerism, and collaborative partnerships:

---

### Candidate 1
* **ID:** 363696
* **Number:** AC-08-28-26
* **Title:** Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants
* **Agency:** AmeriCorps
* **Deadline:** 01/13/2027 (General API deadline; verify applicant-specific routes or state-level commission timelines)
* **Synopsis-Based Reason to Investigate:** AmeriCorps grants are designed specifically for organizations that engage members in service and volunteering to tackle pressing community challenges. Because the applicant is a 501(c)(3) nonprofit operating community volunteer programs, this program directly aligns with mobilizing volunteers, providing living allowances/benefits, and fostering civic engagement.
* **Source Link:** [Grants.gov Opportunity Details](https://www.grants.gov/search-results-detail/363696)

---

### Candidate 2
* **ID:** 358864
* **Number:** PAR-27-015
* **Title:** Community-Based Participatory Research to Advance Data and Practice Transformation (ADAPT) for Optimizing Oral Health for All (UG3/UH3 Clinical Trial Optional)
* **Agency:** Department of Health and Human Services / National Institutes of Health
* **Deadline:** 11/16/2028 (General API deadline)
* **Synopsis-Based Reason to Investigate:** This opportunity supports community-based participatory research (CBPR) and cross-sector partnerships in communities. If the nonprofit's volunteer programs or community initiatives touch upon public health, health disparities, or community wellness, this funding mechanism supports collaborative community engagement and data transformation. *(Note: Full announcement details should be reviewed to confirm alignment with research/health objectives).*
* **Source Link:** [Grants.gov Opportunity Details](https://www.grants.gov/search-results-detail/358864)

---

### Candidate 3
* **ID:** 362062
* **Number:** PD-26-369Y
* **Title:** Engineering Biological and Biomedical Systems (EBBS)
* **Agency:** National Science Foundation
* **Deadline:** Not provided (Open/Rolling solicitation)
* **Synopsis-Based Reason to Investigate:** While this is a scientific research program focused on biological and biomedical systems, the description notes that "limited studies involving human volunteers may be supported if appropriate to the project objectives." However, because this is an engineering and biotechnology research grant rather than a general community volunteer program, its fit depends entirely on whether the nonprofit operates specialized scientific or health-related research activities involving volunteers. 
* **Source Link:** [Grants.gov Opportunity Details](https://www.grants.gov/search-results-detail/362062)

---

*Important Note:* Please check the full notice of funding opportunity (NOFO) on Grants.gov and verify all eligibility requirements, cost-sharing/matching expectations, and application deadlines before deciding whether to apply.

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## 3. Repeat search using the saved profile

**Input**

> Using my saved profile, search again. Do not change my profile.

Observed elapsed time: 8.02 seconds.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Additional federal grant opportunities for a California 501(c)(3) nonprofit running community volunteer programs"}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "community volunteer programs", "rows": 3}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "volunteers community service", "rows": 3}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "volunteer engagement AmeriCorps", "rows": 3}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363696}`.

**Final coordinator answer (verbatim)**

**Nonprofit profile**

- **Organization type:** 501(c)(3) nonprofit
- **Organization location:** California
- **Project purpose:** Community volunteer programs
- **Service area:** Unknown
- **Beneficiaries:** Unknown
- **Requested funding:** Unknown
- **Project timing:** Unknown

---

Based on the search for federal grant opportunities related to community volunteer programs, one relevant candidate was found and evaluated via the Grants.gov API. 

### Research Findings and Candidate Opportunity

* **ID:** 363696
* **Number:** AC-08-28-26
* **Title:** Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants
* **Agency:** AmeriCorps
* **API Deadline:** 01/13/2027 (Label: API's general deadline; any applicant-specific route/deadline remains unverified).
* **Synopsis-Based Reason to Investigate:** This opportunity directly aligns with organizations dedicated to community improvement through service and volunteering. It awards grants to eligible 501(c)(3) nonprofits that engage members in evidence-based interventions to strengthen communities and foster civic engagement.
* **Source Link:** https://www.grants.gov/search-results-detail/363696

*Note: Please check the full notice and associated documentation on Grants.gov before deciding eligibility.*

### Unknown Profile Details That Could Affect Matching
* **Service Area:** The saved profile has `service_area=null`, so it is unknown whether the nonprofit operates statewide in California or within a specific local community, which may impact state-level subgrant allocations or local priority areas.
* **Funding Amount & Timing:** Both `funding_amount_usd` and `project_timing` are unspecified in the profile, making it difficult to assess cost-matching feasibility (AmeriCorps grants typically require cost sharing) or alignment with project start dates.
* **Beneficiaries:** The specific target population served by the volunteer programs is unknown.

***

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## Earlier retest and additional correction

The [first routing retest](04-handoff-recovery-first-observation.json) verified
nonempty child returns, but its last coordinator rewrite omitted the findings.
Its `checks_passed` flag reflects those narrower checks, not user-facing answer
quality. We preserved it as an observation rather than treating it as the final result.

The coordinator now adds the profile summary in Python and appends the saved
researcher findings. The final retest above additionally verifies that the
displayed coordinator answer ends with those saved findings. Regression tests
check that a source link and deadline caveat survive delivery without another
coordinator model request.

## Limits

These times are individual observations, not a latency benchmark. A completed
handoff establishes delivery of findings; it does not prove that a candidate
is a good match. Full-notice verification, eligibility checks, scoring, and
critic review remain planned.
