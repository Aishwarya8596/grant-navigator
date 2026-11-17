# Example 06: Eligibility analyst with source-bound checks

Live session started: 2026-11-13T08:58:40.692334-08:00 (America/Los_Angeles).

Model: `gemini-3.5-flash-lite`, temperature 0, analyst output limit 4,096 tokens. These are actual local ADK Web `/run_sse` requests using real Grants.gov detail calls and the reviewed November 10 PDF snapshot. The same session was used for both turns, with a 65-second pause between them for the observed quota.

Selected machine-readable evidence: [actual prompts, tool calls, source records, raw drafts, accepted reports, and outcomes](06-eligibility-analyst.json).

## Verification scope

Two targeted live smoke scenarios verify three-agent delivery, source-bound requirement checks, unknown preservation, profile-version freshness, and a selected-mechanism conflict. This is not held-out model evaluation, a user study, complete notice review, or confirmed eligibility.

The analyst runs as an ADK dynamic node after research. Its events appear under `eligibility_analyst`; it is not a coordinator-callable tool in the initial static diagram. The source-only node input excludes the researcher's generated prose. Python validates the returned draft and renders accepted checks before appending the saved researcher findings without another model rewrite.

The researcher findings remain generated prose awaiting the planned critic. The accepted report does not certify every statement in the final response.

## 1. Missing facts stay unknown

**Input**

> We are a California 501(c)(3) nonprofit running community volunteer programs. Investigate Grants.gov AmeriCorps opportunity 363696 (AC-08-28-26). Read its notice and assess the requirements supported by the available evidence. Do not assume where our project operates.

Observed elapsed time: 17.46 seconds. Profile version: 1.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{"organization_location": "California", "organization_type": "501(c)(3) nonprofit", "project_purpose": "Community volunteer programs"}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Investigate Grants.gov AmeriCorps opportunity 363696 (AC-08-28-26), read its notice, and assess requirements based on available evidence."}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363696}`.
- `opportunity_researcher` called `read_grant_notice` with `{"focus": "deadlines application route eligibility state commission cost sharing matching rules", "max_excerpts": 8, "opportunity_id": 363696}`.

The next runtime author was `eligibility_analyst`; its structured draft was accepted by the application validator. The final coordinator response was assembled without another coordinator model call.

**Accepted rule checks**

| Check | Status | Source pages |
|---|---|---|
| applicant_type | met | 8 |
| application_route | needs_verification | 8 |
| sam_registration | needs_verification | 8 |
| uei | needs_verification | 8 |
| grant_type | needs_verification | 8 |
| cost_sharing | needs_verification | 7 |
| deadline | needs_verification | 1 |
| source_currentness | needs_verification | No accepted rule quote |

Overall status: `needs_verification`. Blocking scope: `None`.

Current amendments, complete notice review, and the applicant-specific deadline remain unverified. The service area remains unknown; the California headquarters was not reused as project geography.

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

## Eligibility assessment

Assessment date: 2026-11-13.

Assessed 1 researched opportunity; eligibility remains unconfirmed.

### Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants

Opportunity: [AC-08-28-26](https://www.grants.gov/search-results-detail/363696)

**Overall finding: Needs verification**

The opportunity needs further verification. Requirement checks reflect stated facts and selected notice passages, not a final eligibility decision.

API general date: **2027-01-13** (future relative to the assessment date). The applicant-specific deadline remains unverified.

| Requirement | Finding | Basis |
|---|---|---|
| Applicant type | Met on stated facts | The stated nonprofit organization type is supported by the cited applicant-category passage; this does not establish overall eligibility. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Application route | Needs verification | Missing facts prevent this assessment: service area, planned submission route. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| SAM registration | Needs verification | Missing facts prevent this assessment: sam registration active. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Valid UEI | Needs verification | Missing facts prevent this assessment: has valid uei. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Grant type | Needs verification | Missing facts prevent this assessment: americorps grant type, americorps new applicant. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Cost sharing | Needs verification | Missing facts prevent this assessment: americorps grant type. [PDF p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7) |
| Applicable deadline | Needs verification | The API and notice provide general deadline context, but the applicant-specific deadline and route have not been verified. [PDF p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1) |
| Notice version and completeness | Needs verification | The source is a dated or partial review; current amendments and the complete requirement list remain unverified.  |

**Questions to resolve**

- Where will the project operate, and do you plan to apply through a state commission or directly?
- Which grant type are you considering, is this a new applicant, and can any applicable matching requirement be met?
- Is SAM registration active, and does the organization have a valid UEI?

These checks use stated facts and selected notice evidence. Source completeness, current amendments, and overall eligibility still require verification.

---

### Candidate Worth Investigating

* **ID:** 363696
* **Opportunity Number:** AC-08-28-26
* **Title:** Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants
* **Agency:** Rebecca Curtis Grantor
* **API Deadline:** January 13, 2027 12:00:00 AM EST (Notice states: "Applications are due not later than Wednesday, January 13, 2027 by 5:00 p.m. Eastern Time" [Full notice, PDF page 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1)).
* **Synopsis-based reason to investigate:** The nonprofit's project purpose is community volunteer programs, and the organization type is a 501(c)(3) nonprofit, which aligns directly with AmeriCorps State and National grants that engage members in evidence-based interventions to strengthen communities through service and volunteering.
* **Source Link:** https://www.grants.gov/search-results-detail/363696

---

### Summary of Notice Requirements & Unresolved Rules

* **Applicant Route & Deadlines:** The notice specifies that organizations planning to operate in only one state must apply through their state or territory service commission and follow any earlier commission-specific deadlines [Full notice, PDF page 1, 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1). Multi-state (National Direct) applicants apply directly to AmeriCorps [Full notice, PDF page 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8).
* **Cost Sharing & Matching:** Cost reimbursement grants require a 24 percent match for first-time successful applicants during their first three-year funding period, increasing gradually over time [Full notice, PDF page 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7). Fixed amount grants have no cost share or matching requirement, but new applicants are not eligible for full cost fixed amount grants [Full notice, PDF page 7, 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7).

---

### Unknown Profile Details Affecting Matching

* **Service Area:** The project service area is unknown (saved profile specifies `service_area=null`), which leaves the single-state versus multi-state applicant route undetermined. Single-state projects must apply through the relevant state service commission and comply with its schedule.
* **Matching Capability:** It is unknown whether the organization can meet cost-sharing and matching requirements (`can_meet_match=null`).
* **SAM Registration & UEI Status:** Active SAM registration and a valid Unique Entity Identifier status are currently unknown.

*This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.*

## 2. A conflict scoped to the selected mechanism

**Input**

> We are a new AmeriCorps applicant and we are considering a full-cost fixed-amount grant. Our SAM registration is active and we have a valid UEI. Update those facts and reassess the same AmeriCorps opportunity 363696 (AC-08-28-26). Explain whether any issue affects this chosen grant type or the entire opportunity.

Observed elapsed time: 15.07 seconds. Profile version: 2.

**Actual tool sequence**

- `grant_navigator` called `save_nonprofit_profile` with `{"americorps_grant_type": "full_cost_fixed_amount", "americorps_new_applicant": true, "has_valid_uei": true, "sam_registration_active": true}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "Review AmeriCorps opportunity 363696 (AC-08-28-26) specifically regarding new applicant restrictions on full-cost fixed-amount grants."}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363696}`.
- `opportunity_researcher` called `read_grant_notice` with `{"focus": "deadlines application route eligibility cost sharing new applicant restrictions full cost fixed amount state commission", "max_excerpts": 8, "opportunity_id": 363696}`.

The next runtime author was `eligibility_analyst`; its structured draft was accepted by the application validator. The final coordinator response was assembled without another coordinator model call.

**Accepted rule checks**

| Check | Status | Source pages |
|---|---|---|
| applicant_type | met | 8 |
| application_route | needs_verification | 8 |
| sam_registration | met | 8 |
| uei | met | 8 |
| grant_type | not_met | 8 |
| cost_sharing | needs_verification | 7 |
| deadline | needs_verification | 1 |
| source_currentness | needs_verification | No accepted rule quote |

Overall status: `blocking_issue`. Blocking scope: `selected_grant_type`.

Current amendments, complete notice review, and the applicant-specific deadline remain unverified. The service area remains unknown; the California headquarters was not reused as project geography.

The draft's matching-rule proposal did not establish the condition for the selected mechanism. The validator kept cost sharing unresolved (`conditional_matching_unverified`). A genuine page reference alone did not turn that check into a supported finding.

**Final coordinator output (verbatim)**

**Nonprofit profile**

- **Organization type:** 501(c)(3) nonprofit
- **Organization location:** California
- **Project purpose:** Community volunteer programs
- **Service area:** Unknown
- **Beneficiaries:** Unknown
- **Requested funding:** Unknown
- **Project timing:** Unknown
- **SAM registration active:** Yes
- **Valid UEI held:** Yes
- **Selected AmeriCorps grant type:** full cost fixed amount
- **New AmeriCorps applicant (stated):** Yes

---

**Notice sources retrieved**

- **AC-08-28-26:** Notice excerpts retrieved ([p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1), [p. 6](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=6), [p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7), [p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8), [p. 9](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=9), [p. 23](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=23)); saved snapshot, captured 2026-11-10.

These are selected excerpts. Current amendments, applicant-specific deadlines, and eligibility remain unverified.

---

## Eligibility assessment

Assessment date: 2026-11-13.

Assessed 1 researched opportunity; eligibility remains unconfirmed.

### Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants

Opportunity: [AC-08-28-26](https://www.grants.gov/search-results-detail/363696)

**Overall finding: Selected grant-type conflict**

The selected grant-type option conflicts with the cited new-applicant restriction; other options and overall eligibility remain unverified.

API general date: **2027-01-13** (future relative to the assessment date). The applicant-specific deadline remains unverified.

| Requirement | Finding | Basis |
|---|---|---|
| Applicant type | Met on stated facts | The stated nonprofit organization type is supported by the cited applicant-category passage; this does not establish overall eligibility. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Application route | Needs verification | Missing facts prevent this assessment: service area, planned submission route. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| SAM registration | Met on stated facts | The profile states that SAM registration is active; the cited passage requires it. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Valid UEI | Met on stated facts | The profile states that a valid UEI is held; the cited passage requires it. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Grant type | Not met / action needed | The stated new-applicant status conflicts with the quoted restriction on full-cost fixed-amount grants. This blocks that selected grant type, not every grant type in the notice. [PDF p. 8](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=8) |
| Cost sharing | Needs verification | The selected fixed-amount mechanism needs its own matching-rule passage; the API boolean alone is insufficient. [PDF p. 7](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=7) |
| Applicable deadline | Needs verification | The API and notice provide general deadline context, but the applicant-specific deadline and route have not been verified. [PDF p. 1](https://www.oregon.gov/oregonserves/americorps/Documents/2026-27%20Competitive%20Grant%20Documents/FY27_ASNCompetitiveNotice_Final.508.pdf#page=1) |
| Notice version and completeness | Needs verification | The source is a dated or partial review; current amendments and the complete requirement list remain unverified.  |

**Selected-option issue:** The stated new-applicant status conflicts with the quoted restriction on full-cost fixed-amount grants. This blocks that selected grant type, not every grant type in the notice.

**Actions to address**

- Confirm the selected grant mechanism and the applicant's new or returning status.

**Questions to resolve**

- Where will the project operate, and do you plan to apply through a state commission or directly?
- Which grant type are you considering, is this a new applicant, and can any applicable matching requirement be met?
- What is the current applicant-specific deadline for your confirmed submission route?

These checks use stated facts and selected notice evidence. Source completeness, current amendments, and overall eligibility still require verification.

---

### Candidate Worth Investigating

- **ID:** 363696
- **Number:** AC-08-28-26
- **Title:** Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants
- **Agency:** Rebecca Curtis Grantor
- **API Deadline:** January 13, 2027, 5:00 p.m. Eastern Time (API response date listed as January 13, 2027)
- **Synopsis-Based Reason to Investigate:** The opportunity supports community volunteer programs and national service interventions. Since the nonprofit profile specifies a 501(c)(3) organization interested in full-cost fixed-amount grants, this notice directly addresses those parameters and sets out specific eligibility rules for new applicants.
- **Source Link:** https://www.grants.gov/search-results-detail/363696

---

### Research Findings & Notice Rules

Based on the reviewed notice snapshot (`FY27_ASNCompetitiveNotice_Final.508.pdf`), the specific restrictions and requirements regarding new applicants and full-cost fixed-amount grants are as follows:

1. **New Applicant Restrictions on Full-Cost Fixed-Amount Grants:** 
   The notice explicitly states: *"New applicants are eligible to apply for cost reimbursement, Education Award Program (EAP), and Professional Corps grants, but are not eligible to apply for full cost fixed amount grants"* [Notice p. 8]. Furthermore, during initial compliance and eligibility reviews, AmeriCorps checks whether applicants are *"eligible to apply for a Full Cost Fixed Grant"* [Notice p. 23].

2. **Available Grant Types for New Applicants:** 
   Organizations that have not received prior funding from AmeriCorps may apply for Cost Reimbursement, Education Award Program (EAP), and Professional Corps grants [Notice p. 6, 8].

3. **Application Route and Deadlines:** 
   - **Federal Deadline:** Applications are due no later than Wednesday, January 13, 2027, by 5:00 p.m. Eastern Time [Notice p. 1].
   - **Single-State Applicants / State Commissions:** Because the nonprofit is located in California and the project service area is currently unknown (not specified in the profile), any single-state applicant must contact the state service commission where they intend to operate. State service commissions may set deadlines well in advance of the federal AmeriCorps deadline [Notice p. 1, 8].

4. **Matching Requirements:** 
   - For Cost Reimbursement grants, a first-time successful applicant is required to match at 24 percent for the first three-year funding period [Notice p. 7].
   - Fixed-amount grants do not carry a cost share or matching requirement [Notice p. 7], but as noted above, new applicants are barred from applying for full-cost fixed-amount grants.

---

### Unresolved Rules & Missing Facts

- **Service Area & Application Route:** The saved nonprofit profile does not specify a project service area (`service_area = null`). Since single-state projects must apply through the respective State Service Commission (e.g., California Volunteers), the exact submission route, state-level deadlines, and commission-specific guidelines remain unverified.
- **Prior Funding Status:** While the profile indicates the organization is a new AmeriCorps applicant (`americorps_new_applicant = True`), any past sub-grantee history or federal funding background must be officially verified against AmeriCorps records to ensure compliance with new applicant definitions.

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## Earlier schema failures retained

- [SDK conversion observation](06-analyst-schema-observation.json): `exclusiveMinimum` was rejected before the analyst HTTP request.
- [Remote field rejection](06-analyst-api-schema-observation.json): the API rejected `additional_properties` in `response_schema`.
- [Generic constraint rejection](06-analyst-schema-constraint-observation.json): the next API attempt returned a generic HTTP 400 without field-level details.

The final generation schema removes titles, defaults, and string/array bounds as well as the unsupported extra-properties keyword. The application still enforces the original strict draft schema. An isolated live schema probe and both end-to-end scenarios then passed. The generic error did not identify which individual constraint was rejected.

## Separate offline evidence

The final offline suite passed **276 tests**. The [17-case frozen benchmark](../docs/evaluation.md) passed all developer-curated validation cases. Those use constructed drafts; they do not measure Gemini accuracy or user usefulness. The two elapsed times above are individual observations, not a latency benchmark.

Still planned: critic with bounded revisions, fit ranking, broader reviewed notices, held-out model evaluation, and task-based user/proxy testing.
