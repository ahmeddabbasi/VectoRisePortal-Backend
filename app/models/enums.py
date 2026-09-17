from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    EMPLOYEE = "employee"


class EmployeeStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AttendanceStatus(str, Enum):
    ON_TIME = "on_time"
    LATE = "late"
    EARLY = "early"
    ABSENT = "absent"
    INCOMPLETE = "incomplete"
    ON_LEAVE = "on_leave"


class CheckEventType(str, Enum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"


class ScheduleStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    LOCKED = "locked"


class ScheduleChangeStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TaskStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class ExceptionType(str, Enum):
    MISSING_CHECK_IN = "missing_check_in"
    MISSING_CHECK_OUT = "missing_check_out"
    LATE_CHECK_IN = "late_check_in"
    EARLY_CHECK_OUT = "early_check_out"
    LATE_CHECK_OUT = "late_check_out"
    LATE_SCHEDULE = "late_schedule"
    SCHEDULE_CHANGE = "schedule_change"
    OVERDUE_TASK = "overdue_task"
    EXCESSIVE_HOURS = "excessive_hours"
    ATTENDANCE_DISCREPANCY = "attendance_discrepancy"


class NotificationType(str, Enum):
    ATTENDANCE = "attendance"
    SCHEDULE = "schedule"
    TASK = "task"
    EXCEPTION = "exception"
    ANNOUNCEMENT = "announcement"
    SYSTEM = "system"
