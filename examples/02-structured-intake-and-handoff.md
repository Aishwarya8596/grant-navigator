# Structured intake and researcher handoff

Observed: November 12, 2026 (America/Los_Angeles).

This is an actual three-turn run through the local ADK Web `/run_sse` endpoint
with streaming requested, Gemini `gemini-3.5-flash-lite`, temperature 0, and
live Grants.gov calls. It uses a demonstration nonprofit profile. Only selected
prompts, outputs, tool arguments, and state fields are preserved; no credentials
or private session configuration are included.

Raw selected evidence: [successful run](02-intake-session.json).

The prototype now has two agents. Eligibility analysis, full-notice evidence,
fit ranking, and critic review remain planned. Timings below are individual
observations, not benchmarks or evidence of matching accuracy.

## 1. Missing organization details

**Input**

> Find federal grants for our organization.

Observed elapsed time: 1.89 seconds.

**Actual tool calls**

- `grant_navigator` called `save_nonprofit_profile` with `{}`.

**Final coordinator response (verbatim)**

Welcome to the federal grant navigator! I would be glad to help you find federal funding opportunities. 

To help me match you with relevant grants, could you tell me a little bit about your organization and your project? Specifically:

1. What type of organization is applying (for example, a 501(c)(3) nonprofit, local government agency, etc.)?
2. What specific activities or project would you like the grant to fund? 

*(If you also have a specific location, service area, or target population in mind, feel free to share those as well!)*

**Profile after this turn**

```json
{
  "organization_name": null,
  "organization_type": null,
  "organization_location": null,
  "project_purpose": null,
  "service_area": null,
  "beneficiaries": null,
  "funding_amount_usd": null,
  "project_timing": null
}
```

## 2. Complete minimum intake and live research

**Input**

> We are a California 501(c)(3) nonprofit running community volunteer programs. Find posted federal grant opportunities worth investigating.

Observed elapsed time: 8.04 seconds.

**Actual tool calls**

- `grant_navigator` called `save_nonprofit_profile` with `{"organization_location": "California", "organization_type": "501(c)(3) nonprofit", "project_purpose": "Community volunteer programs"}`.
- `grant_navigator` called `opportunity_researcher` with `{"request": "federal grants for community volunteer programs for a California 501(c)(3) nonprofit"}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "community volunteer programs", "rows": 10}`.
- `opportunity_researcher` called `search_grants` with `{"keyword": "volunteer service community engagement", "rows": 10}`.
- `opportunity_researcher` called `fetch_grant_details` with `{"opportunity_id": 363696}`.

**Final coordinator response (verbatim)**

Here is a summary of your organization's profile and the federal grant opportunity identified for your project:

### **Your Profile Summary**
* **Organization Type:** 501(c)(3) nonprofit
* **Organization Location:** California
* **Project Purpose:** Community volunteer programs
* **Service Area:** Unknown *(HQ location does not automatically establish project service area)*
* **Beneficiaries:** Unknown
* **Funding Amount Requested:** Unknown
* **Project Timing:** Unknown

---

### **Candidate Opportunity**

* **ID:** 363696
* **Number:** AC-08-28-26
* **Title:** Fiscal Year (FY) 2027 AmeriCorps State and National Competitive Grants
* **Agency:** AmeriCorps
* **API General Deadline:** 01/13/2027 *(Note: The applicant-specific deadline remains unverified; please check the formal notice on Grants.gov).*
* **Why investigate:** This opportunity aligns with community volunteer programs, providing support to engage members in civic engagement and community service.
* **Source Link:** [Grants.gov Details Page](https://www.grants.gov/search-results-detail/363696)

---

### **Unresolved Questions / Next Steps**
To help narrow down or find additional matching opportunities, it would be helpful to clarify:
1. What is your specific project service area (e.g., a specific county or city in California)?
2. Who are the primary beneficiaries of your volunteer programs (e.g., youth, seniors, veterans)?

*This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.*

**Profile after this turn**

```json
{
  "organization_name": null,
  "organization_type": "501(c)(3) nonprofit",
  "organization_location": "California",
  "project_purpose": "Community volunteer programs",
  "service_area": null,
  "beneficiaries": null,
  "funding_amount_usd": null,
  "project_timing": null
}
```

## 3. Correction without another search

**Input**

> Correction: our project serves seniors in Santa Clara County. Update my profile only; do not search again yet.

Observed elapsed time: 1.72 seconds.

**Actual tool calls**

- `grant_navigator` called `save_nonprofit_profile` with `{"beneficiaries": "Seniors", "service_area": "Santa Clara County"}`.

**Final coordinator response (verbatim)**

I have successfully updated your nonprofit profile with your service area and beneficiaries. 

Here is your updated profile:
* **Organization Type:** 501(c)(3) nonprofit
* **Organization Location:** California
* **Project Purpose:** Community volunteer programs
* **Service Area:** Santa Clara County
* **Beneficiaries:** Seniors
* **Funding Amount Requested:** Unknown
* **Project Timing:** Unknown

Let me know whenever you are ready to search for new grants using this updated profile!

**Profile after this turn**

```json
{
  "organization_name": null,
  "organization_type": "501(c)(3) nonprofit",
  "organization_location": "California",
  "project_purpose": "Community volunteer programs",
  "service_area": "Santa Clara County",
  "beneficiaries": "Seniors",
  "funding_amount_usd": null,
  "project_timing": null
}
```

## Review and limitations

- Turn 1 asked for organization type and project purpose and made no Grants.gov call.
- Turn 2 saved the profile, delegated to the researcher, made two searches and
  one detail request, and returned opportunity 363696. Service area, beneficiaries,
  funding amount, and timing remained unknown.
- Turn 3 updated only service area and beneficiaries, retained the earlier facts,
  cleared the old research summary, and made no new search.
- Both agent names appeared in the Web event stream. No error events were returned.
- The grant remains a discovery candidate. The full notice and the applicant-specific
  deadline have not been checked by these agents. No strongest-match claim is supported.

## Earlier observation that prompted a revision

An initial live run completed the handoff but saved `service_area="California"`
from a user statement that only established the nonprofit's location. The first
coordinator answer also omitted the researcher's explicit general-deadline label.
That output is preserved in [the initial observation](02-intake-first-observation.json)
and is not treated as a fully correct result.

We added concrete extraction examples, set temperature to 0, reinforced deadline
wording, restarted the confirmed development server, and reran the same three prompts.
The successful run above kept service area unknown until the user supplied it.
One successful retest does not prove extraction reliability; more varied profiles
and structured source-backed output checks remain evaluation work.
