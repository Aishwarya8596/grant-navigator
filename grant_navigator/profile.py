"""Validated intake data, independent of the model and Grants.gov."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


REQUIRED_DISCOVERY_FIELDS = ("organization_type", "project_purpose")
MATCHING_FIELDS = ("service_area", "beneficiaries", "funding_amount_usd", "project_timing")
ELIGIBILITY_FIELDS = (
    "sam_registration_active", "has_valid_uei", "planned_submission_route",
    "americorps_grant_type", "americorps_new_applicant", "can_meet_match",
)
FIELD_QUESTIONS = {
    "organization_type": "What type of organization is applying (for example, a 501(c)(3) nonprofit)?",
    "project_purpose": "What activities or project would the grant fund?",
}
UNKNOWN_TEXT = {
    "", "unknown", "unspecified", "not specified", "not provided",
    "not sure", "none", "null", "n/a", "tbd",
}


class NonprofitProfile(BaseModel):
    """User-supplied facts; discovery readiness does not establish eligibility.

    Headquarters and project service area are separate. Unspecified values
    remain null. Funding is an amount in USD, not an inferred award range.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    organization_name: str | None = Field(default=None, max_length=300)
    organization_type: str | None = Field(default=None, max_length=500)
    organization_location: str | None = Field(default=None, max_length=500)
    project_purpose: str | None = Field(default=None, max_length=2000)
    service_area: str | None = Field(default=None, max_length=1000)
    beneficiaries: str | None = Field(default=None, max_length=1000)
    funding_amount_usd: float | None = Field(default=None, ge=0)
    project_timing: str | None = Field(default=None, max_length=1000)
    sam_registration_active: StrictBool | None = None
    has_valid_uei: StrictBool | None = None
    planned_submission_route: Literal["state_commission", "direct"] | None = None
    americorps_grant_type: Literal[
        "cost_reimbursement", "full_cost_fixed_amount", "education_award_program",
        "professional_corps", "fixed_amount_unspecified",
    ] | None = None
    americorps_new_applicant: StrictBool | None = None
    can_meet_match: StrictBool | None = None

    @field_validator(
        "organization_name", "organization_type", "organization_location",
        "project_purpose", "service_area", "beneficiaries", "project_timing",
        "planned_submission_route", "americorps_grant_type",
        mode="before",
    )
    @classmethod
    def normalize_unknown_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.casefold() in UNKNOWN_TEXT:
                return None
        return value

    @field_validator("funding_amount_usd", mode="before")
    @classmethod
    def reject_boolean_amount(cls, value):
        if isinstance(value, bool):
            raise ValueError("funding_amount_usd must be an amount, not true/false")
        return value

    def discovery_status(self) -> dict:
        missing = [field for field in REQUIRED_DISCOVERY_FIELDS if getattr(self, field) is None]
        return {
            "ready_for_research": not missing,
            "missing_required_fields": missing,
            "follow_up_questions": [FIELD_QUESTIONS[field] for field in missing],
            "unknown_matching_fields": [
                field for field in MATCHING_FIELDS if getattr(self, field) is None
            ],
            "unknown_eligibility_fields": [
                field for field in ELIGIBILITY_FIELDS if getattr(self, field) is None
            ],
        }
