from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y")

SENT_INITIAL = {"sent", "replied"}
SENT_FOLLOW = {"sent", "follow-up sent", "follow-up required", "replied", "no response"}
SENT_LINKEDIN = {"sent", "replied", "no response"}
REPLY_MARKERS = {"replied"}


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def get_cell(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        for k, v in row.items():
            if normalize_key(k) == normalize_key(key):
                return str(v or "").strip()
    return ""


def parse_bool(value: str) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "1", "YES"}


def parse_date(value: str) -> date | None:
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def normalize_linkedin_url(url: str) -> str:
    url = str(url or "").strip().lower()
    url = url.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
    return url


def duplicate_key(email: str, linkedin: str, company: str, contact: str) -> str | None:
    if email and "@" in email:
        return f"email:{email.lower()}"
    if linkedin:
        return f"linkedin:{normalize_linkedin_url(linkedin)}"
    if company and contact:
        return f"company:{normalize_key(company)}|{normalize_key(contact)}"
    if company:
        return f"company:{normalize_key(company)}"
    return None


def derive_lead_stage(
    initial: str,
    follow: str,
    linkedin: str,
    reply_status: str,
) -> str:
    blob = f"{initial} {follow} {linkedin} {reply_status}".lower()
    if reply_status.lower() in REPLY_MARKERS or "repl" in blob:
        return "Replied"
    if linkedin:
        return "LinkedIn Follow-up"
    if follow.lower() in SENT_FOLLOW:
        return "Follow-up"
    if initial.lower() in SENT_INITIAL:
        return "Initial Email"
    return "Not Contacted"


def derive_linkedin_stage(replied: bool, outreach_date: date | None) -> str:
    if replied:
        return "Replied"
    if outreach_date:
        return "Awaiting Reply"
    return "Not Contacted"


def build_activities_from_lead_row(row: dict[str, str]) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    initial = get_cell(row, "Initial Email").lower()
    follow = get_cell(row, "Follow-up Email").lower()
    li = get_cell(row, "LinkedIn Follow-up").lower()
    reply_status = get_cell(row, "Reply Status").lower()

    if initial in SENT_INITIAL:
        activities.append(
            {
                "activity_type": "INITIAL_EMAIL",
                "activity_date": parse_date(get_cell(row, "Initial Email Date")),
            }
        )
    if follow in SENT_FOLLOW:
        activities.append(
            {
                "activity_type": "FOLLOW_UP",
                "activity_date": parse_date(get_cell(row, "Follow-up Email Date")),
            }
        )
    if li in SENT_LINKEDIN:
        activities.append(
            {
                "activity_type": "LINKEDIN_FOLLOW_UP",
                "activity_date": parse_date(get_cell(row, "LinkedIn Date")),
            }
        )
    if reply_status in REPLY_MARKERS or any("repl" in x for x in [initial, follow, li]):
        activities.append(
            {
                "activity_type": "REPLY_RECEIVED",
                "activity_date": parse_date(get_cell(row, "Reply Date")),
            }
        )
    meeting_status = get_cell(row, "Meeting Status")
    if meeting_status:
        activities.append(
            {
                "activity_type": "MEETING_BOOKED",
                "activity_date": parse_date(get_cell(row, "Meeting Date")),
            }
        )
    return [a for a in activities if a.get("activity_date")]


def build_activities_from_linkedin_row(row: dict[str, str]) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    outreach_date = parse_date(get_cell(row, "Date"))
    replied = parse_bool(get_cell(row, "Replied")) or parse_bool(get_cell(row, "Reached"))
    if outreach_date:
        activities.append(
            {"activity_type": "LINKEDIN_OUTREACH", "activity_date": outreach_date}
        )
    if replied:
        reply_date = parse_date(get_cell(row, "Reply Date")) or outreach_date
        if reply_date:
            activities.append(
                {"activity_type": "REPLY_RECEIVED", "activity_date": reply_date}
            )
    return activities


def row_to_lead_record(
    row: dict[str, str],
    *,
    row_number: int,
    source: dict[str, Any],
    employee_id: int,
    spreadsheet_id: str,
) -> dict[str, Any] | None:
    first = get_cell(row, "First Name", "Name", "Contact Name")
    if not first:
        return None

    last = get_cell(row, "Last Name")
    company = get_cell(row, "Company Name")
    email = get_cell(row, "Email", "Emails")
    linkedin = get_cell(row, "Person Linkedin Url", "LinkedIn")
    contact_name = " ".join(x for x in [first, last] if x).strip()
    external_id = get_cell(row, "Lead ID") or f"{source['sheet_gid']}-{row_number:04d}"

    if source["data_type"] == "linkedin":
        outreach_date = parse_date(get_cell(row, "Date"))
        replied = parse_bool(get_cell(row, "Replied")) or parse_bool(get_cell(row, "Reached"))
        current_stage = derive_linkedin_stage(replied, outreach_date)
        reply_status = "Replied" if replied else None
        activities = build_activities_from_linkedin_row(row)
    else:
        initial = get_cell(row, "Initial Email")
        follow = get_cell(row, "Follow-up Email")
        li = get_cell(row, "LinkedIn Follow-up")
        reply_status = get_cell(row, "Reply Status") or None
        current_stage = get_cell(row, "Current Stage") or derive_lead_stage(
            initial, follow, li, reply_status or ""
        )
        activities = build_activities_from_lead_row(row)

    activity_dates = [a["activity_date"] for a in activities if a.get("activity_date")]
    last_activity_date = max(activity_dates) if activity_dates else None

    return {
        "external_id": external_id,
        "company_name": company or None,
        "contact_name": contact_name,
        "email": email or None,
        "linkedin_url": linkedin or None,
        "industry": get_cell(row, "Industry") or None,
        "category": source["category"],
        "employee_id": employee_id,
        "current_stage": current_stage,
        "reply_status": reply_status,
        "meeting_status": get_cell(row, "Meeting Status") or None,
        "opportunity_status": get_cell(row, "Opportunity Status") or None,
        "source_sheet": source.get("sheet_title") or source["name"],
        "source_sheet_id": spreadsheet_id,
        "source_row": row_number,
        "source_gid": source["sheet_gid"],
        "last_activity_date": last_activity_date,
        "next_follow_up_date": parse_date(get_cell(row, "Next Follow-up Date")),
        "activities": activities,
        "duplicate_key": duplicate_key(email, linkedin, company, contact_name),
    }
