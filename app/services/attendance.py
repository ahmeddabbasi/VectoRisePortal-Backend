from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.attendance_record import AttendanceRecord
from app.models.employee import Employee
from app.models.enums import AttendanceStatus, CheckEventType, ExceptionType
from app.models.time_session import TimeSession
from app.models.user import User
from app.models.work_schedule import WorkSchedule
from app.services.audit import AuditService
from app.services.exceptions import ExceptionService
from app.services.notifications import NotificationService
from app.services.settings_service import SettingsService


class AttendanceService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = SettingsService(db)
        self.exceptions = ExceptionService(db)
        self.notifications = NotificationService(db)
        self.audit = AuditService(db)

    def _parse_time(self, value: str) -> time:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))

    def _get_schedule_for_date(self, employee_id: int, work_date: date) -> WorkSchedule | None:
        week_start = work_date - timedelta(days=work_date.weekday())
        return (
            self.db.query(WorkSchedule)
            .filter(
                WorkSchedule.employee_id == employee_id,
                WorkSchedule.week_start == week_start,
                WorkSchedule.day_of_week == work_date.weekday(),
            )
            .first()
        )

    def _scheduled_times(self, employee_id: int, work_date: date) -> tuple[datetime | None, datetime | None]:
        schedule = self._get_schedule_for_date(employee_id, work_date)
        if schedule and schedule.is_working_day and schedule.start_time and schedule.end_time:
            return (
                datetime.combine(work_date, schedule.start_time),
                datetime.combine(work_date, schedule.end_time),
            )
        start = self._parse_time(self.settings.get("default_start_time", "09:00"))
        end = self._parse_time(self.settings.get("default_end_time", "17:00"))
        return datetime.combine(work_date, start), datetime.combine(work_date, end)

    def get_or_create_record(self, employee_id: int, work_date: date | None = None) -> AttendanceRecord:
        work_date = work_date or date.today()
        record = (
            self.db.query(AttendanceRecord)
            .filter(AttendanceRecord.employee_id == employee_id, AttendanceRecord.work_date == work_date)
            .first()
        )
        if record:
            return record
        scheduled_start, scheduled_end = self._scheduled_times(employee_id, work_date)
        record = AttendanceRecord(
            employee_id=employee_id,
            work_date=work_date,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            status=AttendanceStatus.INCOMPLETE,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def check_in(self, employee: Employee, user: User | None = None) -> dict:
        now = datetime.utcnow()
        work_date = now.date()
        record = self.get_or_create_record(employee.id, work_date)
        if record.check_in_at:
            raise HTTPException(status_code=400, detail="Already checked in today")

        grace = self.settings.get_int("check_in_grace_minutes", 15)
        scheduled_start = record.scheduled_start
        if not scheduled_start:
            scheduled_start, _ = self._scheduled_times(employee.id, work_date)
            record.scheduled_start = scheduled_start

        grace_end = scheduled_start + timedelta(minutes=grace)
        check_in_status = AttendanceStatus.ON_TIME
        locked = False

        if now < scheduled_start:
            check_in_status = AttendanceStatus.ON_TIME
        elif now <= grace_end:
            check_in_status = AttendanceStatus.LATE
        else:
            check_in_status = AttendanceStatus.LATE
            locked = True
            exc = self.exceptions.create(
                employee.id,
                ExceptionType.LATE_CHECK_IN,
                "Late check-in",
                f"Check-in attempted at {now.isoformat()} after grace period.",
                "attendance_record",
                record.id,
            )
            if user:
                self.notifications.create(
                    user.id,
                    "Late check-in recorded",
                    "Your check-in was after the grace period. An exception has been created for admin review.",
                    "attendance",
                    "/employee/attendance",
                )

        if locked:
            raise HTTPException(
                status_code=403,
                detail="Check-in window closed. Contact admin for exception review.",
            )

        record.check_in_at = now
        record.check_in_status = check_in_status
        record.status = AttendanceStatus.ON_TIME if check_in_status == AttendanceStatus.ON_TIME else AttendanceStatus.LATE

        session = TimeSession(
            employee_id=employee.id,
            attendance_record_id=record.id,
            session_type=CheckEventType.CHECK_IN,
            started_at=now,
        )
        self.db.add(session)
        if user:
            self.audit.log("check_in", user, "attendance_record", record.id, None, {"check_in_at": now.isoformat()})
        self.db.flush()
        return {"record": record, "status": check_in_status, "session": session}

    def check_out(self, employee: Employee, user: User | None = None) -> dict:
        now = datetime.utcnow()
        work_date = now.date()
        record = self.get_or_create_record(employee.id, work_date)
        if not record.check_in_at:
            raise HTTPException(status_code=400, detail="Must check in before checking out")
        if record.check_out_at:
            raise HTTPException(status_code=400, detail="Already checked out today")

        grace = self.settings.get_int("check_out_grace_minutes", 15)
        scheduled_end = record.scheduled_end
        if not scheduled_end:
            _, scheduled_end = self._scheduled_times(employee.id, work_date)
            record.scheduled_end = scheduled_end

        grace_end = scheduled_end + timedelta(minutes=grace)
        if now < scheduled_end - timedelta(minutes=grace):
            checkout_status = AttendanceStatus.EARLY
        elif now <= grace_end:
            checkout_status = AttendanceStatus.ON_TIME
        else:
            checkout_status = AttendanceStatus.LATE
            self.exceptions.create(
                employee.id,
                ExceptionType.LATE_CHECK_OUT,
                "Late checkout",
                f"Checkout at {now.isoformat()} after grace period.",
                "attendance_record",
                record.id,
            )

        record.check_out_at = now
        record.check_out_status = checkout_status
        if record.check_in_at:
            record.total_minutes = int((now - record.check_in_at).total_seconds() // 60)

        open_session = (
            self.db.query(TimeSession)
            .filter(
                TimeSession.employee_id == employee.id,
                TimeSession.attendance_record_id == record.id,
                TimeSession.ended_at.is_(None),
            )
            .first()
        )
        if open_session:
            open_session.ended_at = now
            open_session.duration_minutes = int((now - open_session.started_at).total_seconds() // 60)

        if user:
            self.audit.log("check_out", user, "attendance_record", record.id, None, {"check_out_at": now.isoformat()})
        self.db.flush()
        return {"record": record, "status": checkout_status}

    def admin_correct(
        self,
        record_id: int,
        admin: User,
        check_in_at: datetime | None = None,
        check_out_at: datetime | None = None,
        status: str | None = None,
        reason: str = "",
    ):
        record = self.db.get(AttendanceRecord, record_id)
        if not record:
            raise HTTPException(status_code=404, detail="Attendance record not found")
        previous = {
            "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
            "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
            "status": record.status,
        }
        if check_in_at:
            record.check_in_at = check_in_at
        if check_out_at:
            record.check_out_at = check_out_at
        if status:
            record.status = status
        record.is_corrected = True
        record.corrected_by = admin.id
        record.correction_reason = reason
        if record.check_in_at and record.check_out_at:
            record.total_minutes = int((record.check_out_at - record.check_in_at).total_seconds() // 60)
        self.audit.log("attendance_corrected", admin, "attendance_record", record.id, previous, {
            "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
            "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
            "status": record.status,
        }, reason)
        return record

    def list_records(self, employee_id: int | None = None, start: date | None = None, end: date | None = None):
        q = self.db.query(AttendanceRecord)
        if employee_id:
            q = q.filter(AttendanceRecord.employee_id == employee_id)
        if start:
            q = q.filter(AttendanceRecord.work_date >= start)
        if end:
            q = q.filter(AttendanceRecord.work_date <= end)
        return q.order_by(AttendanceRecord.work_date.desc()).all()

    def today_summary(self) -> dict:
        today = date.today()
        records = self.db.query(AttendanceRecord).filter(AttendanceRecord.work_date == today).all()
        total_employees = self.db.query(Employee).filter(Employee.status == "active").count()
        present = sum(1 for r in records if r.check_in_at)
        late = sum(1 for r in records if r.check_in_status == AttendanceStatus.LATE)
        missing_checkout = sum(1 for r in records if r.check_in_at and not r.check_out_at)
        absent = max(total_employees - present, 0)
        working = sum(1 for r in records if r.check_in_at and not r.check_out_at)
        return {
            "date": today.isoformat(),
            "total_employees": total_employees,
            "present": present,
            "absent": absent,
            "late": late,
            "currently_working": working,
            "missing_checkout": missing_checkout,
        }
