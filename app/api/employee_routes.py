from datetime import date, timedelta

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings

from app.core.deps import require_employee
from app.database import get_db
from app.models.employee import Employee
from app.models.task import Task
from app.models.task_checklist_item import TaskChecklistItem
from app.models.user import User
from app.schemas.hrm import (
    AttendanceRecordOut,
    ChecklistItemOut,
    EmployeeOut,
    ExceptionExplain,
    ExceptionOut,
    NotificationOut,
    PerformanceScoreOut,
    ProfileUpdate,
    ScheduleChangeIn,
    ScheduleSubmit,
    EmployeeTaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.services.attendance import AttendanceService
from app.services.audit import AuditService
from app.services.exceptions import ExceptionService
from app.services.notifications import NotificationService
from app.services.performance import PerformanceService
from app.services.schedule import ScheduleService
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/employee", tags=["employee"])


def _require_employee_record(user: User, db: Session) -> Employee:
    if not user.employee_id:
        raise HTTPException(status_code=403, detail="No employee profile linked")
    employee = db.get(Employee, user.employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.get("/dashboard")
def employee_dashboard(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    attendance_svc = AttendanceService(db)
    task_svc = TaskService(db)
    schedule_svc = ScheduleService(db)
    today = date.today()
    record = attendance_svc.get_or_create_record(employee.id, today)
    week_start = today - timedelta(days=today.weekday())
    schedules = schedule_svc.get_week_schedules(employee.id, week_start + timedelta(days=7))
    task_summary = task_svc.task_summary(employee.id)
    notifications = NotificationService(db).list_for_user(user.id, unread_only=True, limit=5, days=3)
    return {
        "date": today.isoformat(),
        "employee": {"id": employee.id, "name": employee.name, "job_title": employee.job_title},
        "attendance": AttendanceRecordOut.model_validate(record),
        "is_checked_in": bool(record.check_in_at and not record.check_out_at),
        "tasks": task_summary,
        "schedule_submitted": len(schedules) > 0,
        "notifications": [NotificationOut.model_validate(n) for n in notifications],
        "weekly_tasks_completed": task_summary["completed"],
    }


@router.get("/profile", response_model=EmployeeOut)
def get_profile(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    from app.models.department import Department
    dept = db.get(Department, employee.department_id) if employee.department_id else None
    return EmployeeOut(
        id=employee.id,
        employee_code=employee.employee_code,
        name=employee.name,
        email=employee.email,
        phone=employee.phone,
        job_title=employee.job_title,
        department_id=employee.department_id,
        role=employee.role,
        status=employee.status,
        joining_date=employee.joining_date,
        profile_photo_url=employee.profile_photo_url,
        department_name=dept.name if dept else None,
    )


@router.put("/profile", response_model=EmployeeOut)
def update_profile(payload: ProfileUpdate, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    if payload.phone is not None:
        employee.phone = payload.phone
    if payload.profile_photo_url is not None:
        employee.profile_photo_url = payload.profile_photo_url
    AuditService(db).log("profile_updated", user, "employee", employee.id)
    db.commit()
    return get_profile(user, db)


@router.post("/attendance/check-in")
def check_in(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    result = AttendanceService(db).check_in(employee, user)
    db.commit()
    return {"status": result["status"], "record": AttendanceRecordOut.model_validate(result["record"])}


@router.post("/attendance/check-out")
def check_out(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    result = AttendanceService(db).check_out(employee, user)
    db.commit()
    return {"status": result["status"], "record": AttendanceRecordOut.model_validate(result["record"])}


@router.get("/attendance", response_model=list[AttendanceRecordOut])
def my_attendance(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    records = AttendanceService(db).list_records(employee.id, start=date.today() - timedelta(days=90))
    return records


@router.post("/schedule/submit")
def submit_schedule(payload: ScheduleSubmit, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    ScheduleService(db).submit_week(employee, payload.week_start, [d.model_dump() for d in payload.days], user)
    db.commit()
    return {"status": "submitted", "week_start": payload.week_start.isoformat()}


@router.get("/schedule")
def get_schedule(week_start: date, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    schedules = ScheduleService(db).get_week_schedules(employee.id, week_start)
    return schedules


@router.post("/schedule/change-request")
def schedule_change(payload: ScheduleChangeIn, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    request = ScheduleService(db).request_change(employee, payload.schedule_id, payload.reason, payload.proposed_changes)
    db.commit()
    return {"status": "pending", "id": request.id}


@router.get("/tasks", response_model=list[TaskOut])
def my_tasks(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    tasks = TaskService(db).list_tasks(employee.id)
    result = []
    for task in tasks:
        out = TaskOut.model_validate(task)
        items = sorted(task.checklist_items, key=lambda i: i.sort_order)
        out.checklist_items = [ChecklistItemOut.model_validate(i) for i in items]
        result.append(out)
    return result


@router.post("/tasks", response_model=TaskOut)
def create_my_task(payload: EmployeeTaskCreate, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    task = TaskService(db).create_employee_task(employee.id, user, payload.model_dump())
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.put("/tasks/{task_id}")
def update_my_task(task_id: int, payload: TaskUpdate, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    task = db.get(Task, task_id)
    if not task or task.assigned_employee_id != employee.id:
        raise HTTPException(status_code=404, detail="Task not found")
    updated = TaskService(db).update_task(
        task_id, payload.model_dump(exclude_unset=True), user, employee_owned=True
    )
    db.commit()
    return TaskOut.model_validate(updated)


@router.post("/tasks/{task_id}/checklist/{item_id}/toggle")
def toggle_checklist(task_id: int, item_id: int, completed: bool = True, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    task = db.get(Task, task_id)
    if not task or task.assigned_employee_id != employee.id:
        raise HTTPException(status_code=404, detail="Task not found")
    TaskService(db).toggle_checklist_item(item_id, completed, user)
    db.commit()
    return {"status": "ok"}


@router.post("/tasks/{task_id}/timer/start")
def start_timer(task_id: int, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    log = TaskService(db).start_timer(task_id, employee.id)
    db.commit()
    return {"id": log.id, "started_at": log.started_at.isoformat()}


@router.post("/tasks/timer/{log_id}/stop")
def stop_timer(log_id: int, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    log = TaskService(db).stop_timer(log_id, employee.id)
    db.commit()
    return {"id": log.id, "duration_minutes": log.duration_minutes}


@router.post("/profile/photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    user: User = Depends(require_employee),
    db: Session = Depends(get_db),
):
    employee = _require_employee_record(user, db)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_upload_mb}MB limit")
    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    filename = f"{employee.id}_{uuid.uuid4().hex}{ext}"
    dest = settings.upload_path / "profile" / filename
    dest.write_bytes(content)
    employee.profile_photo_url = f"/uploads/profile/{filename}"
    AuditService(db).log("profile_photo_uploaded", user, "employee", employee.id)
    db.commit()
    return {"profile_photo_url": employee.profile_photo_url}


@router.get("/exceptions", response_model=list[ExceptionOut])
def my_exceptions(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    return ExceptionService(db).list_exceptions(employee.id)


@router.post("/exceptions/{exception_id}/explain")
def explain_exception(exception_id: int, payload: ExceptionExplain, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    from app.models.exception_record import ExceptionRecord
    record = db.get(ExceptionRecord, exception_id)
    if not record or record.employee_id != user.employee_id:
        raise HTTPException(status_code=404, detail="Exception not found")
    record.employee_explanation = payload.explanation
    record.status = "under_review"
    db.commit()
    return {"status": "ok"}


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    return NotificationService(db).list_for_user(user.id, days=3)


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user: User = Depends(require_employee), db: Session = Depends(get_db)):
    NotificationService(db).mark_read(notification_id, user.id)
    db.commit()
    return {"status": "ok"}


@router.get("/performance")
def my_performance(user: User = Depends(require_employee), db: Session = Depends(get_db)):
    employee = _require_employee_record(user, db)
    end = date.today()
    start = end - timedelta(days=30)
    metrics = PerformanceService(db).employee_metrics(employee.id, start, end)
    from app.models.performance_score import PerformanceScore
    from app.models.hr_evaluation import HREvaluation
    scores = (
        db.query(PerformanceScore)
        .filter(PerformanceScore.employee_id == employee.id)
        .order_by(PerformanceScore.created_at.desc())
        .limit(10)
        .all()
    )
    evaluations = (
        db.query(HREvaluation)
        .filter(HREvaluation.employee_id == employee.id)
        .order_by(HREvaluation.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        **metrics,
        "score_history": [
            {"period_end": str(s.period_end), "total_score": s.total_score, "breakdown": s.breakdown}
            for s in scores
        ],
        "evaluations": [
            {"score": e.score, "comments": e.comments, "period_end": str(e.period_end)}
            for e in evaluations
        ],
    }
