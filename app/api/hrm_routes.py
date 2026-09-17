from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.task import Task
from app.models.task_checklist_item import TaskChecklistItem
from app.models.user import User
from app.models.employee import Employee
from app.models.schedule_change_request import ScheduleChangeRequest
from app.schemas.hrm import (
    AttendanceCorrect,
    AttendanceRecordEnriched,
    AttendanceRecordOut,
    ChecklistItemOut,
    ExceptionEnriched,
    ExceptionOut,
    ExceptionResolve,
    ScheduleChangeOut,
    ScheduleChangeReview,
    TaskCreate,
    TaskOut,
    TaskReject,
    TaskUpdate,
)
from app.services.attendance import AttendanceService
from app.services.exceptions import ExceptionService
from app.services.schedule import ScheduleService
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/hrm", tags=["hrm"])


def _employee_map(db: Session) -> dict[int, str]:
    return {e.id: e.name for e in db.query(Employee).all()}


@router.get("/attendance", response_model=list[AttendanceRecordEnriched])
def list_attendance(
    employee_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    from datetime import timedelta

    names = _employee_map(db)
    if not start and not end:
        end = date.today()
        start = end - timedelta(days=90)
    records = AttendanceService(db).list_records(employee_id, start, end)[:limit]
    result = []
    for record in records:
        out = AttendanceRecordEnriched.model_validate(record)
        out.employee_name = names.get(record.employee_id)
        result.append(out)
    return result


@router.get("/attendance/summary")
def attendance_summary(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return AttendanceService(db).today_summary()


@router.put("/attendance/{record_id}/correct")
def correct_attendance(record_id: int, payload: AttendanceCorrect, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    record = AttendanceService(db).admin_correct(
        record_id, admin, payload.check_in_at, payload.check_out_at, payload.status, payload.reason
    )
    db.commit()
    return AttendanceRecordOut.model_validate(record)


@router.get("/exceptions", response_model=list[ExceptionEnriched])
def list_exceptions(
    employee_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    names = _employee_map(db)
    records = ExceptionService(db).list_exceptions(employee_id, status)
    result = []
    for record in records:
        out = ExceptionEnriched.model_validate(record)
        out.employee_name = names.get(record.employee_id)
        result.append(out)
    return result


@router.post("/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: int, payload: ExceptionResolve, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    record = ExceptionService(db).resolve(exception_id, admin, payload.status, payload.admin_response)
    db.commit()
    return ExceptionOut.model_validate(record)


@router.get("/tasks", response_model=list[TaskOut])
def list_all_tasks(
    employee_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    tasks = TaskService(db).list_tasks(employee_id, status)
    result = []
    for task in tasks:
        out = TaskOut.model_validate(task)
        items = sorted(task.checklist_items, key=lambda i: i.sort_order)
        out.checklist_items = [ChecklistItemOut.model_validate(i) for i in items]
        result.append(out)
    return result


@router.post("/tasks", response_model=TaskOut)
def create_task(payload: TaskCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    task = TaskService(db).create_task(payload.model_dump(), admin)
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    task = TaskService(db).update_task(task_id, payload.model_dump(exclude_unset=True), admin)
    db.commit()
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/approve", response_model=TaskOut)
def approve_task(task_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    task = TaskService(db).approve_task(task_id, admin)
    db.commit()
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/reject", response_model=TaskOut)
def reject_task(task_id: int, payload: TaskReject, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    task = TaskService(db).reject_task(task_id, admin, payload.reason)
    db.commit()
    return TaskOut.model_validate(task)


@router.get("/schedules")
def list_schedules(
    employee_id: int | None = None,
    week_start: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    from app.models.work_schedule import WorkSchedule
    names = _employee_map(db)
    q = db.query(WorkSchedule)
    if employee_id:
        q = q.filter(WorkSchedule.employee_id == employee_id)
    if week_start:
        q = q.filter(WorkSchedule.week_start == week_start)
    rows = q.order_by(WorkSchedule.week_start.desc()).limit(200).all()
    return [
        {
            "id": r.id,
            "employee_id": r.employee_id,
            "employee_name": names.get(r.employee_id),
            "week_start": r.week_start,
            "day_of_week": r.day_of_week,
            "is_working_day": r.is_working_day,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "break_minutes": r.break_minutes,
            "status": r.status,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/schedules/lock")
def lock_schedules(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    locked = ScheduleService(db).lock_expired_schedules()
    db.commit()
    return {"locked_count": len(locked)}


@router.get("/schedule-changes", response_model=list[ScheduleChangeOut])
def list_schedule_changes(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    names = _employee_map(db)
    q = db.query(ScheduleChangeRequest)
    if status:
        q = q.filter(ScheduleChangeRequest.status == status)
    rows = q.order_by(ScheduleChangeRequest.created_at.desc()).limit(100).all()
    result = []
    for row in rows:
        out = ScheduleChangeOut.model_validate(row)
        out.employee_name = names.get(row.employee_id)
        result.append(out)
    return result


@router.post("/schedule-changes/{request_id}/review")
def review_schedule_change(
    request_id: int,
    payload: ScheduleChangeReview,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    record = ScheduleService(db).review_change(request_id, admin, payload.status, payload.admin_response)
    db.commit()
    return ScheduleChangeOut.model_validate(record)


@router.post("/jobs/daily")
def run_daily_jobs(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from app.services.attendance_jobs import AttendanceJobService
    result = AttendanceJobService(db).run_daily_jobs()
    db.commit()
    return result


@router.get("/reports")
def hrm_reports(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    from datetime import timedelta

    from sqlalchemy import func

    from app.models.attendance_record import AttendanceRecord
    from app.models.performance_score import PerformanceScore

    today = date.today()
    week_ago = today - timedelta(days=7)
    task_stats = TaskService(db).dashboard_stats()
    employee_count = db.query(func.count(Employee.id)).filter(Employee.status == "active").scalar() or 0
    from sqlalchemy import case

    trend_rows = (
        db.query(
            AttendanceRecord.work_date,
            func.sum(case((AttendanceRecord.check_in_at.isnot(None), 1), else_=0)),
        )
        .filter(AttendanceRecord.work_date >= week_ago, AttendanceRecord.work_date <= today)
        .group_by(AttendanceRecord.work_date)
        .order_by(AttendanceRecord.work_date)
        .all()
    )
    scores = db.query(PerformanceScore).order_by(PerformanceScore.created_at.desc()).limit(20).all()
    return {
        "attendance_trend": [{"date": str(d), "present": int(present)} for d, present in trend_rows],
        "task_stats": task_stats,
        "employee_count": employee_count,
        "recent_scores": [
            {"employee_id": s.employee_id, "total_score": s.total_score, "period_end": str(s.period_end)}
            for s in scores
        ],
    }
