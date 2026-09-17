from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    employee_id: int | None = None
    is_active: bool
    name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    employee_id: int | None = None
    name: str | None = None
    email: str


class LoginRequest(BaseModel):
    email: str
    password: str


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None = None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


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


class EmployeeCreate(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=8)
    phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    role: str = "employee"
    joining_date: date | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    status: str | None = None
    role: str | None = None


class ProfileUpdate(BaseModel):
    phone: str | None = None
    profile_photo_url: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class ScheduleDayIn(BaseModel):
    day_of_week: int
    is_working_day: bool = True
    start_time: str | None = "09:00"
    end_time: str | None = "17:00"
    break_minutes: int = 60
    availability: str | None = None
    notes: str | None = None


class ScheduleSubmit(BaseModel):
    week_start: date
    days: list[ScheduleDayIn]


class ScheduleChangeIn(BaseModel):
    schedule_id: int | None = None
    reason: str
    proposed_changes: str


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


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: str = "medium"
    assigned_employee_id: int
    due_date: date | None = None
    estimated_minutes: int | None = None
    task_type: str | None = "general"
    notes: str | None = None
    auto_checklist: bool = True


class EmployeeTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: str = "medium"
    due_date: date | None = None
    task_type: str | None = "general"
    notes: str | None = None


class TaskReject(BaseModel):
    reason: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    due_date: date | None = None
    estimated_minutes: int | None = None
    status: str | None = None
    progress: int | None = None
    notes: str | None = None


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


class ExceptionExplain(BaseModel):
    explanation: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    notification_type: str
    title: str
    message: str
    link: str | None = None
    is_read: bool
    created_at: datetime


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


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


class ScheduleChangeReview(BaseModel):
    status: str
    admin_response: str | None = None


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
