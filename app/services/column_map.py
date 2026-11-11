"""Map sheet headers onto the columns the lead pipeline already understands."""

import re
from dataclasses import dataclass

_SPACE = re.compile(r"\s+")


def _key(value: str) -> str:
    return _SPACE.sub(" ", str(value or "").strip().lower())


@dataclass(frozen=True)
class SystemField:
    key: str
    label: str
    canonical: str
    required: bool
    aliases: tuple[str, ...]


LEAD_FIELDS = (
    SystemField("first_name", "First name", "First Name", True, ("first name", "name", "contact name", "contact")),
    SystemField("last_name", "Last name", "Last Name", False, ("last name", "surname")),
    SystemField("company_name", "Company", "Company Name", False, ("company name", "company", "organization")),
    SystemField("email", "Email", "Email", False, ("email", "emails", "email address")),
    SystemField("linkedin_url", "LinkedIn URL", "Person Linkedin Url", False, ("person linkedin url", "linkedin", "linkedin url")),
    SystemField("industry", "Industry", "Industry", False, ("industry",)),
    SystemField("lead_id", "Lead ID", "Lead ID", False, ("lead id", "id")),
    SystemField("initial_email", "Initial email status", "Initial Email", False, ("initial email",)),
    SystemField("initial_email_date", "Initial email date", "Initial Email Date", False, ("initial email date",)),
    SystemField("follow_up_email", "Follow-up status", "Follow-up Email", False, ("follow-up email", "follow up email")),
    SystemField("follow_up_email_date", "Follow-up date", "Follow-up Email Date", False, ("follow-up email date", "follow up email date")),
    SystemField("linkedin_follow_up", "LinkedIn follow-up status", "LinkedIn Follow-up", False, ("linkedin follow-up", "linkedin follow up")),
    SystemField("linkedin_date", "LinkedIn date", "LinkedIn Date", False, ("linkedin date",)),
    SystemField("reply_status", "Reply status", "Reply Status", False, ("reply status",)),
    SystemField("reply_date", "Reply date", "Reply Date", False, ("reply date",)),
    SystemField("meeting_status", "Meeting status", "Meeting Status", False, ("meeting status",)),
    SystemField("meeting_date", "Meeting date", "Meeting Date", False, ("meeting date",)),
    SystemField("current_stage", "Current stage", "Current Stage", False, ("current stage", "stage")),
)

LINKEDIN_FIELDS = (
    SystemField("first_name", "First name", "First Name", True, ("first name", "name", "contact name")),
    SystemField("company_name", "Company", "Company Name", False, ("company name", "company")),
    SystemField("linkedin_url", "LinkedIn URL", "Person Linkedin Url", False, ("person linkedin url", "linkedin", "linkedin url")),
    SystemField("outreach_date", "Outreach date", "Date", False, ("date", "outreach date")),
    SystemField("replied", "Replied", "Replied", False, ("replied",)),
    SystemField("reached", "Reached", "Reached", False, ("reached",)),
    SystemField("reply_date", "Reply date", "Reply Date", False, ("reply date",)),
)


def fields_for(data_type: str) -> tuple[SystemField, ...]:
    return LINKEDIN_FIELDS if data_type == "linkedin" else LEAD_FIELDS


def suggest_mapping(headers: list[str], data_type: str) -> list[dict]:
    normalized = [(header, _key(header)) for header in headers if str(header).strip()]
    used: set[str] = set()
    suggestions = []
    for field in fields_for(data_type):
        match = ""
        confidence = "none"
        for header, key in normalized:
            if header in used:
                continue
            if key in field.aliases or key == _key(field.canonical):
                match = header
                confidence = "exact"
                break
        if not match:
            for header, key in normalized:
                if header in used:
                    continue
                if any(alias in key or key in alias for alias in field.aliases if len(alias) > 3):
                    match = header
                    confidence = "close"
                    break
        if match:
            used.add(match)
        suggestions.append(
            {
                "field": field.key,
                "label": field.label,
                "required": field.required,
                "canonical": field.canonical,
                "suggested_header": match,
                "confidence": confidence,
            }
        )
    return suggestions


def apply_column_map(row: dict[str, str], column_map: dict[str, str] | None, data_type: str) -> dict[str, str]:
    if not column_map:
        return row
    merged = dict(row)
    by_key = {field.key: field for field in fields_for(data_type)}
    for field_key, header in column_map.items():
        field = by_key.get(field_key)
        if not field or not header:
            continue
        merged[field.canonical] = str(row.get(header, "") or "").strip()
    return merged
