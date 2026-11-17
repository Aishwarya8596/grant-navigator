"""Typed API opportunity facts without inventing applicant-specific rules.

Grants.gov's search status and general response date describe an opportunity.
They do not establish an individual applicant's route, deadline, or eligibility.
Normalization never assigns a new retrieval timestamp to an older fixture.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_UNKNOWN = {"", "none", "null", "n/a", "unknown", "not provided"}
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAMES = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}


class OpportunityRecord(BaseModel):
    """Facts supplied by one identified detail response and optional search hit."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    opportunity_id: int = Field(gt=0)
    opportunity_number: str | None = None
    title: str | None = None
    agency: str | None = None
    description: str | None = None
    opportunity_status: str | None = None
    status_source: Literal["search", "detail", "unavailable"] = "unavailable"
    applicant_types: list[str] = Field(default_factory=list)
    cost_sharing: bool | None = None
    award_floor_raw: str | None = None
    award_ceiling_raw: str | None = None
    award_floor_usd: float | None = Field(default=None, ge=0)
    award_ceiling_usd: float | None = Field(default=None, ge=0)
    api_general_deadline_raw: str | None = None
    api_general_deadline_date: date | None = None
    api_general_deadline_source: Literal["detail_response_date", "search_close_date", "unavailable"] = "unavailable"
    detail_response_date_raw: str | None = None
    search_open_date_raw: str | None = None
    search_open_date: date | None = None
    search_close_date_raw: str | None = None
    search_close_date: date | None = None
    source_page: str
    source_api: str | None = None
    retrieved_at_utc: datetime | None = None
    search_retrieved_at_utc: datetime | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("opportunity_id", "award_floor_usd", "award_ceiling_usd", mode="before")
    @classmethod
    def reject_boolean_numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean values are not opportunity IDs or funding amounts")
        return value

    @field_validator("retrieved_at_utc", "search_retrieved_at_utc")
    @classmethod
    def require_aware_utc(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("retrieval timestamps must include a timezone")
            return value.astimezone(timezone.utc)
        return value


class GeneralDeadlineCheck(BaseModel):
    """A calendar-date comparison, never an applicant-specific deadline verdict."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["past", "on_as_of_date", "future", "unknown"]
    as_of_date: date
    deadline_date: date | None = None
    scope: Literal["api_general"] = "api_general"
    applicant_specific_verified: Literal[False] = False
    note: str = (
        "This compares only the API's general calendar date. Applicant-specific "
        "routes, earlier deadlines, exact times, and amendments remain unverified."
    )


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped.casefold() not in _UNKNOWN else None


def _raw_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _positive_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("opportunity ID must be a positive integer")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        number = int(value.strip())
        if number > 0:
            return number
    raise ValueError("opportunity ID must be a positive integer")


def parse_general_deadline_date(value: Any) -> date | None:
    """Read the source calendar date, discarding no ambiguity by guessing time.

    Supports search dates, ISO dates/timestamps, and detail strings such as
    ``Jan 13, 2027 12:00:00 AM EST``. The API's midnight placeholder is not
    promoted to an applicant-specific due time or converted to a UTC deadline.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        iso = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[ T].*)?", text)
        if iso:
            # Validate a timestamp too; malformed suffixes are not silently
            # accepted as if they were a trusted date-only field.
            if len(text) > 10:
                datetime.fromisoformat(text.replace("Z", "+00:00"))
            return date.fromisoformat(iso.group(1))
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text):
            return datetime.strptime(text, "%m/%d/%Y").date()
        named = re.fullmatch(
            r"([A-Za-z]{3,9})\s*(\d{1,2})\s*,\s*(\d{4})"
            r"(?:\s+(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(AM|PM)(?:\s+[A-Za-z]{2,5})?)?",
            text, flags=re.IGNORECASE,
        )
        if named:
            month_name = named.group(1).casefold()
            if month_name not in _MONTHS and month_name not in _MONTH_NAMES:
                return None
            if named.group(4) and (
                not 1 <= int(named.group(4)) <= 12
                or not 0 <= int(named.group(5) or 0) <= 59
                or not 0 <= int(named.group(6) or 0) <= 59
            ):
                return None
            month = _MONTHS.get(month_name[:3])
            if month:
                return date(int(named.group(3)), month, int(named.group(2)))
    except (ValueError, OverflowError):
        return None
    return None


def _amount(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\$?\s*(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
            return None
        number = float(text.replace("$", "").replace(",", "").strip())
    else:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _retrieval_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("retrieval timestamp must be an ISO datetime with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("retrieval timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_opportunity(
    detail: dict,
    search_hit: dict | None = None,
    retrieved_at: datetime | str | None = None,
) -> OpportunityRecord:
    """Normalize existing wrapper fields; preserve unknowns and source scope.

    ``status='success'`` is transport success, never an opportunity status.
    A status can come from the matching search hit or a separately supplied
    ``opportunity_status`` field. No new timestamp is assigned if none exists.
    """
    if not isinstance(detail, dict) or (search_hit is not None and not isinstance(search_hit, dict)):
        raise ValueError("opportunity detail and search hit must be objects")
    if detail.get("status") not in (None, "success"):
        raise ValueError("only a successful detail response can become opportunity facts")
    hit = search_hit or {}
    opportunity_id = _positive_id(detail.get("id"))
    if hit and _positive_id(hit.get("id")) != opportunity_id:
        raise ValueError("search and detail opportunity IDs do not match")
    number = _text(detail.get("number"))
    search_number = _text(hit.get("number"))
    if number and search_number and number != search_number:
        raise ValueError("search and detail opportunity numbers do not match")

    warnings = []
    floor_raw, ceiling_raw = detail.get("award_floor"), detail.get("award_ceiling")
    floor, ceiling = _amount(floor_raw), _amount(ceiling_raw)
    for label, raw, parsed in (("award_floor", floor_raw, floor), ("award_ceiling", ceiling_raw, ceiling)):
        if raw is not None and parsed is None and not (isinstance(raw, str) and raw.strip().casefold() in _UNKNOWN):
            warnings.append(f"{label} is not a usable nonnegative USD amount.")
    if floor is not None and ceiling is not None and floor > ceiling:
        warnings.append("The API funding range is inconsistent; both parsed bounds remain unknown.")
        floor = ceiling = None

    detail_deadline = _raw_text(detail.get("response_date"))
    search_close = _raw_text(hit.get("close_date"))
    detail_date = parse_general_deadline_date(detail_deadline)
    search_date = parse_general_deadline_date(search_close)
    deadline, deadline_date, deadline_source = detail_deadline, detail_date, "detail_response_date"
    if detail_date is None and search_date is not None:
        deadline, deadline_date, deadline_source = search_close, search_date, "search_close_date"
    elif _text(detail_deadline) is None:
        deadline, deadline_date, deadline_source = search_close, search_date, "search_close_date" if _text(search_close) else "unavailable"
    if detail_date and search_date and detail_date != search_date:
        warnings.append("Detail and search report different general deadline dates; verify the full notice.")
    if deadline is not None and _text(deadline) is not None and deadline_date is None:
        warnings.append("The API general deadline could not be parsed; no date was inferred.")
    if detail_deadline and detail_date is None and search_date is not None and _text(detail_deadline):
        warnings.append("The detail response date was unparseable; the matching search close date is retained as general metadata.")

    detail_status = _text(detail.get("opportunity_status"))
    search_status = _text(hit.get("status"))
    if detail_status and detail_status.casefold() == "success":
        detail_status = None
    if search_status and search_status.casefold() == "success":
        search_status = None
    status = detail_status or search_status
    status_source = "detail" if detail_status else "search" if search_status else "unavailable"
    if detail_status and search_status and detail_status.casefold() != search_status.casefold():
        warnings.append("Detail and search report different opportunity statuses; verify the source before screening.")
    cost_sharing = detail.get("cost_sharing")
    if cost_sharing is not None and not isinstance(cost_sharing, bool):
        warnings.append("The API cost-sharing field is not a boolean; it remains unknown.")
        cost_sharing = None
    applicant_types = detail.get("applicant_types")
    applicants = [_text(item) for item in applicant_types] if isinstance(applicant_types, list) else []
    detail_time = retrieved_at if retrieved_at is not None else detail.get("retrieved_at_utc")
    return OpportunityRecord(
        opportunity_id=opportunity_id,
        opportunity_number=number or search_number,
        title=_text(detail.get("title")) or _text(hit.get("title")),
        agency=_text(detail.get("agency")) or _text(hit.get("agency")),
        description=_text(detail.get("description")),
        opportunity_status=status.casefold() if status else None,
        status_source=status_source,
        applicant_types=[item for item in applicants if item is not None],
        cost_sharing=cost_sharing,
        award_floor_raw=_raw_text(floor_raw), award_ceiling_raw=_raw_text(ceiling_raw),
        award_floor_usd=floor, award_ceiling_usd=ceiling,
        api_general_deadline_raw=deadline,
        api_general_deadline_date=deadline_date,
        api_general_deadline_source=deadline_source,
        detail_response_date_raw=detail_deadline,
        search_open_date_raw=_raw_text(hit.get("open_date")),
        search_open_date=parse_general_deadline_date(hit.get("open_date")),
        search_close_date_raw=search_close, search_close_date=search_date,
        source_page=f"https://www.grants.gov/search-results-detail/{opportunity_id}",
        source_api=_text(detail.get("source_api")),
        retrieved_at_utc=_retrieval_time(detail_time),
        search_retrieved_at_utc=_retrieval_time(hit.get("retrieved_at_utc")),
        warnings=warnings,
    )


def check_general_deadline(
    opportunity: OpportunityRecord,
    as_of: date | str,
) -> GeneralDeadlineCheck:
    """Compare a known general date to an explicit as-of date, not the clock."""
    if isinstance(as_of, datetime):
        raise ValueError("as_of must be a calendar date, not a timestamp")
    if isinstance(as_of, str):
        try:
            as_of = date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO calendar date") from exc
    if not isinstance(as_of, date):
        raise ValueError("as_of must be a calendar date")
    deadline = opportunity.api_general_deadline_date
    status = "unknown" if deadline is None else "past" if deadline < as_of else "future" if deadline > as_of else "on_as_of_date"
    return GeneralDeadlineCheck(status=status, as_of_date=as_of, deadline_date=deadline)
