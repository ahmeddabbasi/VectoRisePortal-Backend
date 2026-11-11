from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.text_guard import (
    ATTENDANCE_STATUSES,
    EMPLOYEE_STATUSES,
    EXCEPTION_REVIEW,
    ROLES,
    SCHEDULE_REVIEW,
    TASK_PRIORITIES,
    TASK_STATUSES,
    normalize_email,
    one_of,
    optional_text,
    require_text,
    validate_password,
    validate_phone,
)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    employee_id: int | None = None
    is_active: bool
    name: str | None = None
    sales_access: bool = False
    can_review_tasks: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    employee_id: int | None = None
    name: str | None = None
    email: str
    sales_access: bool = False
    can_review_tasks: bool = False


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None = None


class DepartmentCreate(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return require_text(value, max_length=100, allow_newlines=False)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=500)


class DepartmentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_text(value, max_length=100, allow_newlines=False)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=500)


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_code: str | None = None
    name: str
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    role: str
    status: str
    joining_date: date | None = None
    profile_photo_url: str | None = None
    department_name: str | None = None
    sales_access: bool = False
    can_review_tasks: bool = False


class EmployeeCreate(BaseModel):
    name: str
    email: str
    password: str
    phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    role: str = "employee"
    joining_date: date | None = None
    sales_access: bool = False
    can_review_tasks: bool = False

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return require_text(value, max_length=120, allow_newlines=False)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def clean_password(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str | None) -> str | None:
        return validate_phone(value)

    @field_validator("job_title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=100, allow_newlines=False)

    @field_validator("role")
    @classmethod
    def clean_role(cls, value: str) -> str:
        role = one_of(value, ROLES)
        if role is None:
            raise ValueError("Unsupported value")
        return role


class EmployeeUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    status: str | None = None
    role: str | None = None
    sales_access: bool | None = None
    can_review_tasks: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_text(value, max_length=120, allow_newlines=False)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_email(value)

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str | None) -> str | None:
        return validate_phone(value)

    @field_validator("job_title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=100, allow_newlines=False)

    @field_validator("status")
    @classmethod
    def clean_status(cls, value: str | None) -> str | None:
        return one_of(value, EMPLOYEE_STATUSES)

    @field_validator("role")
    @classmethod
    def clean_role(cls, value: str | None) -> str | None:
        return one_of(value, ROLES)


class ProfileUpdate(BaseModel):
    phone: str | None = None

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str | None) -> str | None:
        return validate_phone(value)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def clean_password(cls, value: str) -> str:
        return validate_password(value)


class ScheduleDayIn(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    is_working_day: bool = True
    start_time: str | None = "09:00"
    end_time: str | None = "17:00"
    break_minutes: int = Field(default=60, ge=0, le=480)
    availability: str | None = None
    notes: str | None = None

    @field_validator("availability")
    @classmethod
    def clean_availability(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=120, allow_newlines=False)

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=500)


class ScheduleSubmit(BaseModel):
    week_start: date
    days: list[ScheduleDayIn] = Field(min_length=1, max_length=7)


class ScheduleChangeIn(BaseModel):
    schedule_id: int | None = None
    reason: str
    proposed_changes: str

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return require_text(value, max_length=1000)

    @field_validator("proposed_changes")
    @classmethod
    def clean_changes(cls, value: str) -> str:
        return require_text(value, max_length=2000)


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    work_date: date
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    status: str
    check_in_status: str | None = None
    check_out_status: str | None = None
    total_minutes: int | None = None
    is_corrected: bool = False


class AttendanceCorrect(BaseModel):
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    status: str | None = None
    reason: str

    @field_validator("status")
    @classmethod
    def clean_status(cls, value: str | None) -> str | None:
        return one_of(value, ATTENDANCE_STATUSES)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return require_text(value, max_length=500)


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: str = "medium"
    assigned_employee_id: int = Field(gt=0)
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=10000)
    task_type: str | None = "general"
    notes: str | None = None
    auto_checklist: bool = True

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return require_text(value, max_length=255, allow_newlines=False)

    @field_validator("description", "notes")
    @classmethod
    def clean_long(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=4000)

    @field_validator("priority")
    @classmethod
    def clean_priority(cls, value: str) -> str:
        priority = one_of(value, TASK_PRIORITIES)
        if priority is None:
            raise ValueError("Unsupported value")
        return priority

    @field_validator("task_type")
    @classmethod
    def clean_type(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=50, allow_newlines=False)


class EmployeeTaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: str = "medium"
    due_date: date | None = None
    task_type: str | None = "general"
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return require_text(value, max_length=255, allow_newlines=False)

    @field_validator("description", "notes")
    @classmethod
    def clean_long(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=4000)

    @field_validator("priority")
    @classmethod
    def clean_priority(cls, value: str) -> str:
        priority = one_of(value, TASK_PRIORITIES)
        if priority is None:
            raise ValueError("Unsupported value")
        return priority

    @field_validator("task_type")
    @classmethod
    def clean_type(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=50, allow_newlines=False)


class TaskReject(BaseModel):
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=500)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=10000)
    status: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_text(value, max_length=255, allow_newlines=False)

    @field_validator("description", "notes")
    @classmethod
    def clean_long(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=4000)

    @field_validator("priority")
    @classmethod
    def clean_priority(cls, value: str | None) -> str | None:
        return one_of(value, TASK_PRIORITIES)

    @field_validator("status")
    @classmethod
    def clean_status(cls, value: str | None) -> str | None:
        return one_of(value, TASK_STATUSES)


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    sort_order: int
    is_completed: bool
    is_auto_generated: bool


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str | None = None
    priority: str
    assigned_employee_id: int
    due_date: date | None = None
    estimated_minutes: int | None = None
    actual_minutes: int | None = None
    status: str
    progress: int
    task_type: str | None = None
    notes: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    checklist_items: list[ChecklistItemOut] = []


class ExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    exception_type: str
    title: str
    description: str | None = None
    status: str
    employee_explanation: str | None = None
    admin_response: str | None = None
    occurred_at: datetime
    created_at: datetime


class ExceptionResolve(BaseModel):
    status: str
    admin_response: str | None = None

    @field_validator("status")
    @classmethod
    def clean_status(cls, value: str) -> str:
        status = one_of(value, EXCEPTION_REVIEW)
        if status is None:
            raise ValueError("Unsupported value")
        return status

    @field_validator("admin_response")
    @classmethod
    def clean_response(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=2000)


class ExceptionExplain(BaseModel):
    explanation: str

    @field_validator("explanation")
    @classmethod
    def clean_explanation(cls, value: str) -> str:
        return require_text(value, max_length=2000)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    notification_type: str
    title: str
    message: str
    link: str | None = None
    is_read: bool
    created_at: datetime


class AnnouncementCreate(BaseModel):
    title: str
    body: str

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return require_text(value, max_length=255, allow_newlines=False)

    @field_validator("body")
    @classmethod
    def clean_body(cls, value: str) -> str:
        return require_text(value, max_length=5000)


class AnnouncementOut(BaseModel):
    id: int
    title: str
    body: str
    created_by_name: str | None = None
    created_at: datetime
    recipient_count: int | None = None


class PerformanceScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    period_start: date
    period_end: date
    period_type: str
    attendance_score: float
    task_completion_score: float
    deadline_score: float
    schedule_score: float
    evaluation_score: float
    total_score: float
    breakdown: str | None = None


class HREvaluationIn(BaseModel):
    employee_id: int
    period_start: date
    period_end: date
    score: float = Field(ge=0, le=100)
    comments: str | None = None
    evidence: str | None = None

    @field_validator("comments", "evidence")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=4000)


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


class ScheduleChangeReview(BaseModel):
    status: str
    admin_response: str | None = None

    @field_validator("status")
    @classmethod
    def clean_status(cls, value: str) -> str:
        status = one_of(value, SCHEDULE_REVIEW)
        if status is None:
            raise ValueError("Unsupported value")
        return status

    @field_validator("admin_response")
    @classmethod
    def clean_response(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=2000)


class AttendanceRecordEnriched(AttendanceRecordOut):
    employee_name: str | None = None


class ExceptionEnriched(ExceptionOut):
    employee_name: str | None = None


class ScheduleChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    schedule_id: int | None = None
    reason: str
    proposed_changes: str
    status: str
    admin_response: str | None = None
    created_at: datetime
    employee_name: str | None = None
