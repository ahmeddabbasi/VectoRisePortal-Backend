from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.text_guard import optional_text
from app.database import get_db
from app.models.hr_evaluation import HREvaluation
from app.models.task import Task
from app.models.task_document import TaskDocument
from app.models.task_review import TaskReview
from app.models.user import User
from app.schemas.hrm import HREvaluationIn, TaskCreate, TaskOut
from app.services.audit import AuditService
from app.services.hierarchy import HierarchyService
from app.services.task_files import purge_expired_task_documents
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/team", tags=["team"])


class TaskReviewIn(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    comments: str | None = None
    status: str

    @field_validator("status")
    @classmethod
    def clean_status(cls, value: str) -> str:
        if value not in {"approved", "needs_changes"}:
            raise ValueError("Choose approved or needs changes")
        return value

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: str | None) -> str | None:
        return optional_text(value, max_length=4000)


@router.get("/me")
def my_team(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.employee_id:
        return {"team_leads": [], "direct_reports": []}
    return HierarchyService(db).summary(user.employee_id)


@router.get("/people/{employee_id}")
def person_profile(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models.employee import Employee

    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    hierarchy = HierarchyService(db)
    if not hierarchy.can_view_person(user, employee_id):
        raise HTTPException(status_code=403, detail="You cannot view that profile")
    return hierarchy.visible_profile(user, employee)


@router.get("/reports/{employee_id}/tasks", response_model=list[TaskOut])
def report_tasks(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    HierarchyService(db).require_leads(user, employee_id)
    tasks = TaskService(db).list_tasks(employee_id)
    return [TaskOut.model_validate(task) for task in tasks]


@router.post("/reports/{employee_id}/tasks", response_model=TaskOut)
def assign_task(
    employee_id: int,
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    HierarchyService(db).require_leads(user, employee_id)
    data = payload.model_dump()
    data["assigned_employee_id"] = employee_id
    task = TaskService(db).create_task(data, user)
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.get("/tasks/{task_id}/documents")
def report_task_documents(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not HierarchyService(db).can_view_task(user, task):
        raise HTTPException(status_code=403, detail="You cannot view documents for that task")
    if purge_expired_task_documents(db):
        db.commit()
    docs = db.query(TaskDocument).filter(TaskDocument.task_id == task.id).order_by(TaskDocument.id.desc()).all()
    return [
        {
            "id": doc.id,
            "task_id": task.id,
            "original_name": doc.original_name,
            "content_type": doc.content_type,
            "size_bytes": doc.size_bytes,
            "created_at": doc.created_at,
            "expires_at": doc.expires_at,
            "download_path": f"/api/media/tasks/{doc.stored_name}",
        }
        for doc in docs
    ]


@router.post("/tasks/{task_id}/reviews")
def review_task(
    task_id: int,
    payload: TaskReviewIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    HierarchyService(db).require_leads(user, task.assigned_employee_id)
    review = TaskReview(
        task_id=task.id,
        reviewer_user_id=user.id,
        rating=payload.rating,
        comments=payload.comments,
        status=payload.status,
    )
    db.add(review)
    AuditService(db).log("task_reviewed", user, "task", task.id, None, {"status": payload.status})
    db.commit()
    return {"id": review.id, "status": review.status}


@router.post("/reports/{employee_id}/evaluations")
def review_performance(
    employee_id: int,
    payload: HREvaluationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    HierarchyService(db).require_leads(user, employee_id)
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="The review period end is before the start")
    evaluation = HREvaluation(
        employee_id=employee_id,
        evaluator_id=user.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        score=payload.score,
        comments=payload.comments,
        evidence=payload.evidence,
    )
    db.add(evaluation)
    AuditService(db).log("hr_evaluation_created", user, "hr_evaluation", employee_id, None, {"score": payload.score})
    db.commit()
    return {"id": evaluation.id, "period_end": str(evaluation.period_end or date.today())}
