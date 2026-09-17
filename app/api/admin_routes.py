from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.deps import require_admin
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.employee import Employee
from app.models.user import User
from app.schemas.hrm import (
    AnnouncementCreate,
    AnnouncementOut,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    HREvaluationIn,
    PerformanceScoreOut,
    SettingsUpdate,
)
from app.services.announcements import AnnouncementService
from app.services.attendance import AttendanceService
from app.services.audit import AuditService
from app.services.auth import hash_password
from app.services.metrics import MetricsService
from app.services.performance import PerformanceService
from app.services.settings_service import SettingsService
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _employee_out(emp: Employee) -> EmployeeOut:
    dept = emp.department
    return EmployeeOut(
        id=emp.id,
        employee_code=emp.employee_code,
        name=emp.name,
        email=emp.email,
        phone=emp.phone,
        job_title=emp.job_title,
        department_id=emp.department_id,
        role=emp.role,
        status=emp.status,
        joining_date=emp.joining_date,
        profile_photo_url=emp.profile_photo_url,
        department_name=dept.name if dept else None,
    )


@router.get("/dashboard")
def admin_dashboard(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    attendance = AttendanceService(db).today_summary()
    task_stats = TaskService(db).dashboard_stats()
    sales_overview = MetricsService(db).overview("today")
    return {
        "workforce": attendance,
        "tasks": {
            "completed_today": task_stats["completed_today"],
            "overdue": task_stats["overdue"],
            "total_active": task_stats["total_active"],
        },
        "sales": {
            "total_leads": sales_overview.get("total_leads", 0),
            "emails_sent": sales_overview.get("emails_sent", 0),
            "replies": sales_overview.get("replies", 0),
            "meetings": sales_overview.get("meetings", 0),
        },
    }


@router.get("/employees", response_model=list[EmployeeOut])
def list_employees(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    employees = db.query(Employee).options(joinedload(Employee.department)).order_by(Employee.name).all()
    return [_employee_out(e) for e in employees]


@router.post("/employees", response_model=EmployeeOut)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    employee = Employee(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        job_title=payload.job_title,
        department_id=payload.department_id,
        role=payload.role,
        joining_date=payload.joining_date,
        employee_code=f"EMP{db.query(Employee).count() + 1:04d}",
    )
    db.add(employee)
    db.flush()
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        employee_id=employee.id,
    )
    db.add(user)
    AuditService(db).log("employee_created", admin, "employee", employee.id, None, {"name": employee.name})
    db.commit()
    db.refresh(employee)
    return _employee_out(employee)


@router.put("/employees/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, payload: EmployeeUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    previous = {"name": employee.name, "status": employee.status, "email": employee.email}
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        existing = db.query(User).filter(User.email == data["email"]).first()
        if existing and existing.employee_id != employee.id:
            raise HTTPException(status_code=400, detail="Email already in use")
        user = db.query(User).filter(User.employee_id == employee.id).first()
        if user:
            user.email = data["email"]
    for field, value in data.items():
        setattr(employee, field, value)
    AuditService(db).log("employee_updated", admin, "employee", employee.id, previous, data)
    db.commit()
    db.refresh(employee)
    return _employee_out(employee)


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(Department).order_by(Department.name).all()


@router.post("/departments", response_model=DepartmentOut)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(Department).filter(Department.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Department already exists")
    dept = Department(name=payload.name, description=payload.description)
    db.add(dept)
    AuditService(db).log("department_created", admin, "department", None, None, {"name": payload.name})
    db.commit()
    db.refresh(dept)
    return dept


@router.put("/departments/{department_id}", response_model=DepartmentOut)
def update_department(department_id: int, payload: DepartmentUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    if payload.name and payload.name != dept.name:
        if db.query(Department).filter(Department.name == payload.name).first():
            raise HTTPException(status_code=400, detail="Department name already exists")
        dept.name = payload.name
    if payload.description is not None:
        dept.description = payload.description
    AuditService(db).log("department_updated", admin, "department", dept.id)
    db.commit()
    db.refresh(dept)
    return dept


@router.delete("/departments/{department_id}")
def delete_department(department_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    assigned = db.query(Employee).filter(Employee.department_id == department_id).count()
    if assigned:
        raise HTTPException(status_code=400, detail=f"Cannot delete — {assigned} employees assigned")
    db.delete(dept)
    AuditService(db).log("department_deleted", admin, "department", department_id)
    db.commit()
    return {"status": "ok"}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return SettingsService(db).get_all()


@router.put("/settings")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    service = SettingsService(db)
    for key, value in payload.settings.items():
        service.set(key, value)
    AuditService(db).log("settings_updated", admin, "system_settings", None, None, payload.settings)
    db.commit()
    return service.get_all()


@router.get("/audit-logs")
def audit_logs(limit: int = Query(100, le=500), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.post("/evaluations")
def create_evaluation(payload: HREvaluationIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from app.models.hr_evaluation import HREvaluation
    evaluation = HREvaluation(
        employee_id=payload.employee_id,
        evaluator_id=admin.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        score=payload.score,
        comments=payload.comments,
        evidence=payload.evidence,
    )
    db.add(evaluation)
    AuditService(db).log("hr_evaluation_created", admin, "hr_evaluation", payload.employee_id, None, {"score": payload.score})
    db.commit()
    return {"status": "ok", "id": evaluation.id}


@router.get("/performance/scores")
def list_performance_scores(
    employee_id: int | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    from app.models.performance_score import PerformanceScore
    q = db.query(PerformanceScore)
    if employee_id:
        q = q.filter(PerformanceScore.employee_id == employee_id)
    scores = q.order_by(PerformanceScore.created_at.desc()).limit(limit).all()
    names = {e.id: e.name for e in db.query(Employee).all()}
    return [
        {
            "id": s.id,
            "employee_id": s.employee_id,
            "employee_name": names.get(s.employee_id),
            "period_start": s.period_start,
            "period_end": s.period_end,
            "total_score": s.total_score,
            "breakdown": s.breakdown,
        }
        for s in scores
    ]


@router.get("/evaluations")
def list_evaluations(employee_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    from app.models.hr_evaluation import HREvaluation
    q = db.query(HREvaluation)
    if employee_id:
        q = q.filter(HREvaluation.employee_id == employee_id)
    rows = q.order_by(HREvaluation.created_at.desc()).limit(100).all()
    names = {e.id: e.name for e in db.query(Employee).all()}
    return [
        {
            "id": r.id,
            "employee_id": r.employee_id,
            "employee_name": names.get(r.employee_id),
            "period_start": r.period_start,
            "period_end": r.period_end,
            "score": r.score,
            "comments": r.comments,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/announcements", response_model=list[AnnouncementOut])
def list_announcements(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = AnnouncementService(db).list_all()
    users = {u.id: u.email for u in db.query(User).filter(User.id.in_({r.created_by_user_id for r in rows})).all()}
    return [
        AnnouncementOut(
            id=r.id,
            title=r.title,
            body=r.body,
            created_by_name=users.get(r.created_by_user_id),
            created_at=r.created_at,
            recipient_count=None,
        )
        for r in rows
    ]


@router.post("/announcements", response_model=AnnouncementOut)
def create_announcement(
    payload: AnnouncementCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ann = AnnouncementService(db).broadcast(admin, payload.title, payload.body)
    db.commit()
    db.refresh(ann)
    employee_count = db.query(User).filter(User.role == "employee", User.is_active.is_(True)).count()
    return AnnouncementOut(
        id=ann.id,
        title=ann.title,
        body=ann.body,
        created_by_name=admin.email,
        created_at=ann.created_at,
        recipient_count=employee_count,
    )


@router.post("/performance/{employee_id}/calculate", response_model=PerformanceScoreOut)
def calculate_performance(
    employee_id: int,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    end = period_end or date.today()
    start = period_start or (end - timedelta(days=7))
    score = PerformanceService(db).calculate_score(employee_id, start, end)
    db.commit()
    db.refresh(score)
    return score
