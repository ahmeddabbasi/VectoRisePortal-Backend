from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.enums import ExceptionType, ScheduleChangeStatus, ScheduleStatus
from app.models.schedule_change_request import ScheduleChangeRequest
from app.models.user import User
from app.models.work_schedule import WorkSchedule
from app.services.audit import AuditService
from app.services.exceptions import ExceptionService
from app.services.settings_service import SettingsService


class ScheduleService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsService(db)
        self.exceptions = ExceptionService(db)
        self.audit = AuditService(db)

    def next_week_start(self, from_date: date | None = None) -> date:
        from_date = from_date or date.today()
        days_until_monday = (7 - from_date.weekday()) % 7
        if days_until_monday == 0 and from_date.weekday() != 0:
            days_until_monday = 7
        if from_date.weekday() == 0:
            return from_date
        return from_date + timedelta(days=days_until_monday if from_date.weekday() != 0 else 7)

    def get_week_schedules(self, employee_id: int, week_start: date) -> list[WorkSchedule]:
        return (
            self.db.query(WorkSchedule)
            .filter(WorkSchedule.employee_id == employee_id, WorkSchedule.week_start == week_start)
            .order_by(WorkSchedule.day_of_week)
            .all()
        )

    def submit_week(
        self,
        employee: Employee,
        week_start: date,
        days: list[dict],
        user: User | None = None,
    ) -> list[WorkSchedule]:
        existing = self.get_week_schedules(employee.id, week_start)
        if existing and any(s.status == ScheduleStatus.LOCKED for s in existing):
            raise HTTPException(status_code=400, detail="Schedule is locked for this week")

        results = []
        for day in days:
            start_time = time.fromisoformat(day["start_time"]) if day.get("start_time") else None
            end_time = time.fromisoformat(day["end_time"]) if day.get("end_time") else None
            row = (
                self.db.query(WorkSchedule)
                .filter(
                    WorkSchedule.employee_id == employee.id,
                    WorkSchedule.week_start == week_start,
                    WorkSchedule.day_of_week == day["day_of_week"],
                )
                .first()
            )
            if not row:
                row = WorkSchedule(employee_id=employee.id, week_start=week_start, day_of_week=day["day_of_week"])
                self.db.add(row)
            row.is_working_day = day.get("is_working_day", True)
            row.start_time = start_time
            row.end_time = end_time
            row.break_minutes = day.get("break_minutes", 0)
            row.availability = day.get("availability")
            row.notes = day.get("notes")
            row.status = ScheduleStatus.SUBMITTED
            row.submitted_at = datetime.utcnow()
            results.append(row)

        if user:
            self.audit.log("schedule_submitted", user, "work_schedule", employee.id, None, {"week_start": week_start.isoformat()})
        self.db.flush()
        return results

    def lock_expired_schedules(self):
        now = datetime.utcnow()
        deadline_day = self.settings.get_int("schedule_deadline_day", 4)
        deadline_hour = self.settings.get_int("schedule_deadline_hour", 17)
        if now.weekday() != deadline_day or now.hour < deadline_hour:
            return []

        next_week = self.next_week_start(now.date())
        employees = self.db.query(Employee).filter(Employee.status == "active").all()
        locked = []
        for employee in employees:
            schedules = self.get_week_schedules(employee.id, next_week)
            if not schedules:
                self.exceptions.create(
                    employee.id,
                    ExceptionType.LATE_SCHEDULE,
                    "Missed schedule submission",
                    f"No schedule submitted for week starting {next_week.isoformat()}",
                )
                continue
            for schedule in schedules:
                if schedule.status != ScheduleStatus.LOCKED:
                    schedule.status = ScheduleStatus.LOCKED
                    schedule.locked_at = now
                    locked.append(schedule)
        return locked

    def request_change(self, employee: Employee, schedule_id: int | None, reason: str, proposed_changes: str):
        request = ScheduleChangeRequest(
            employee_id=employee.id,
            schedule_id=schedule_id,
            reason=reason,
            proposed_changes=proposed_changes,
            status=ScheduleChangeStatus.PENDING,
        )
        self.db.add(request)
        self.exceptions.create(
            employee.id,
            ExceptionType.SCHEDULE_CHANGE,
            "Schedule change request",
            reason,
            "schedule_change_request",
            None,
        )
        self.db.flush()
        return request

    def review_change(self, request_id: int, admin: User, status: str, admin_response: str | None = None):
        request = self.db.get(ScheduleChangeRequest, request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Request not found")
        request.status = status
        request.admin_response = admin_response
        request.reviewed_by = admin.id
        request.reviewed_at = datetime.utcnow()
        self.audit.log("schedule_change_reviewed", admin, "schedule_change_request", request.id, None, {"status": status})
        return request
