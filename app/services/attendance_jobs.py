from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.attendance_record import AttendanceRecord
from app.models.employee import Employee
from app.models.enums import AttendanceStatus, ExceptionType
from app.services.attendance import AttendanceService
from app.services.exceptions import ExceptionService
from app.services.settings_service import SettingsService


class AttendanceJobService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsService(db)
        self.exceptions = ExceptionService(db)

    def process_end_of_day(self, work_date: date | None = None) -> dict:
        work_date = work_date or date.today()
        employees = self.db.query(Employee).filter(Employee.status == "active").all()
        policy = self.settings.get("incomplete_attendance_policy", "incomplete")
        created = 0
        updated = 0

        for employee in employees:
            record = (
                self.db.query(AttendanceRecord)
                .filter(AttendanceRecord.employee_id == employee.id, AttendanceRecord.work_date == work_date)
                .first()
            )
            if not record:
                record = AttendanceService(self.db).get_or_create_record(employee.id, work_date)
                updated += 1

            if record.check_in_at and not record.check_out_at:
                result = self.exceptions.create(
                    employee.id,
                    ExceptionType.MISSING_CHECK_OUT,
                    "Missing checkout",
                    f"No checkout recorded for {work_date.isoformat()}",
                    "attendance_record",
                    record.id,
                )
                record.status = AttendanceStatus.INCOMPLETE
                if result.created:
                    created += 1
            elif not record.check_in_at and not record.check_out_at:
                status = AttendanceStatus.ABSENT if policy == "absent" else AttendanceStatus.INCOMPLETE
                record.status = status
                result = self.exceptions.create(
                    employee.id,
                    ExceptionType.MISSING_CHECK_IN,
                    "Missing attendance",
                    f"No check-in recorded for {work_date.isoformat()}",
                    "attendance_record",
                    record.id,
                )
                if result.created:
                    created += 1
            elif record.check_in_at and record.check_out_at and record.total_minutes:
                max_daily = self.settings.get_int("daily_max_hours", 10) * 60
                if record.total_minutes > max_daily:
                    result = self.exceptions.create(
                        employee.id,
                        ExceptionType.EXCESSIVE_HOURS,
                        "Excessive working hours",
                        f"Worked {record.total_minutes} minutes on {work_date.isoformat()}",
                        "attendance_record",
                        record.id,
                    )
                    if result.created:
                        created += 1

        return {"date": work_date.isoformat(), "exceptions_created": created, "records_updated": updated}

    def run_daily_jobs(self) -> dict:
        from app.services.schedule import ScheduleService
        locked = ScheduleService(self.db).lock_expired_schedules()
        eod = self.process_end_of_day(date.today() - timedelta(days=1))
        return {"schedules_locked": len(locked), "attendance": eod}
