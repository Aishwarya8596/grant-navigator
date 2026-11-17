"""Prioritize researched grants for investigation using the accepted eligibility report."""

from .eligibility import AnalystInput, EligibilityDraft, EligibilityReport

# The combined audience and geography criterion is worth 25 points.
CRITERIA = {
    "purpose": ("Project purpose", "project_purpose", 40),
    "beneficiaries": ("Beneficiaries", "beneficiaries", 15),
    "service_area": ("Service area", "service_area", 10),
    "timing": ("Project timing", "project_timing", 15),
}


def rank_candidates(inputs: AnalystInput, initial: EligibilityDraft, report: EligibilityReport) -> dict:
    decisions = {d.opportunity_id: d for d in report.decisions}
    ranked, held = [], []
    for candidate in inputs.candidates:
        op = candidate.opportunity
        decision = decisions.get(op.opportunity_id)
        entry = {"id": op.opportunity_id, "title": op.title or op.opportunity_number or str(op.opportunity_id),
                 "source": op.source_page}
        hold = []
        if decision is None:
            hold.append("Eligibility assessment unavailable.")
        elif decision.blocking_scope == "selected_grant_type":
            hold.append("The selected grant type conflicts with a notice rule. Other options need review.")
        if op.opportunity_status in {"closed", "archived", "forecasted"}:
            hold.append(f"The API lists this opportunity as {op.opportunity_status}.")
        if op.api_general_deadline_date and op.api_general_deadline_date < inputs.as_of_date:
            hold.append("The API general date has passed. Verify the applicable deadline.")
        proposals = [d for d in initial.decisions if d.opportunity_id == op.opportunity_id]
        evidence = proposals[0].fit_evidence if len(proposals) == 1 else []
        score = 0
        reasons, unknown, conflicts = [], [], []
        purpose_supported = False
        for dimension, (label, field, weight) in CRITERIA.items():
            facts = [f for f in evidence if f.dimension == dimension]
            fact = facts[0] if len(facts) == 1 else None
            value = getattr(inputs.profile, field)
            if not value or not fact or not fact.synopsis_quote.strip() or fact.synopsis_quote not in (op.description or ""):
                unknown.append(label)
            elif fact.assessment == "conflicts":
                conflicts.append(f"{label} ({value}): “{fact.synopsis_quote}”")
            else:
                score += weight
                reasons.append(f"{label} +{weight} ({value}): “{fact.synopsis_quote}”")
                if dimension == "purpose":
                    purpose_supported = True
        if not purpose_supported:
            hold.append("Project-purpose fit needs supporting evidence or a different project.")
        amount = inputs.profile.funding_amount_usd
        floor, ceiling = op.award_floor_usd, op.award_ceiling_usd
        if amount is not None and ((floor is not None and amount < floor) or
                                   (ceiling is not None and amount > ceiling)):
            conflicts.append(f"Requested ${amount:,.0f} falls outside the published award bounds.")
        elif amount is not None and floor is not None and ceiling is not None:
            score += 20
            reasons.append(f"Funding +20: requested ${amount:,.0f} is within ${floor:,.0f}–${ceiling:,.0f}.")
        else:
            unknown.append("Funding range or requested amount")
        entry.update(points=score, reasons=reasons, unknown=unknown, conflicts=conflicts, hold=hold)
        (held if hold else ranked).append(entry)
    ranked.sort(key=lambda item: (bool(item["conflicts"]), -item["points"], item["id"]))
    return {"invocation_id": inputs.invocation_id, "profile_version": inputs.profile_version,
            "ranked": ranked[:3], "held": held}


def render_ranking(result):
    lines = ["**Grants to investigate first**", "",
             "Fit points reflect the evidence available for your project. Eligibility and applicant deadlines still need verification."]
    if not result["ranked"]:
        lines.append("No researched option is ready to prioritize for this project.")
    for position, item in enumerate(result["ranked"], 1):
        lines.extend(["", f"{position}. **[{item['title']}]({item['source']})** — {item['points']}/100 fit points"])
        lines.extend("   - " + reason for reason in item["reasons"])
        lines.extend("   - Conflict: " + issue for issue in item["conflicts"])
        if item["unknown"]:
            lines.append("   - Could change this placement: " + ", ".join(item["unknown"]) + ".")
    for item in result["held"]:
        lines.append(f"\n**Set aside for verification or another option:** [{item['title']}]({item['source']}) — "
                     + " ".join(item["hold"] + item["conflicts"]))
    return "\n".join(lines)
