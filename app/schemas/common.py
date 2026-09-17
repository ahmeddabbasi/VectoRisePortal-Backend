from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str


class SyncStatusResponse(BaseModel):
    status: str
    last_sync_at: datetime | None = None
    message: str | None = None
    rows_processed: int | None = None
    leads_upserted: int | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    company_name: str | None
    contact_name: str | None
    email: str | None
    linkedin_url: str | None
    industry: str | None
    category: str
    current_stage: str | None
    reply_status: str | None
    meeting_status: str | None
    opportunity_status: str | None
    source_sheet: str
    source_row: int
    last_activity_date: date | None
    next_follow_up_date: date | None
    is_duplicate: bool
    employee_name: str | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_type: str
    activity_date: date | None
    source: str
    notes: str | None = None


class LeadDetailResponse(LeadResponse):
    activities: list[ActivityResponse] = []


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None
    role: str
    status: str


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    employee_name: str
    category: str
    spreadsheet_id: str
    sheet_gid: int
    sheet_title: str | None
    data_type: str
    is_active: bool
    last_sync_at: datetime | None
    last_sync_status: str | None
