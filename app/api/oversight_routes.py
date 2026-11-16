import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import SessionLocal, get_db
from app.models.user import User
from app.services.oversight import OversightService, _activity_item

router = APIRouter(prefix="/api/oversight", tags=["oversight"])


def _service(user: User, db: Session) -> OversightService:
    return OversightService(db, user)


def _page(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    return page, page_size


@router.get("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _service(user, db).summary()


@router.get("/teams")
def teams(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    sort: str = "name",
    direction: str = "asc",
    date_from: date | None = None,
    date_to: date | None = None,
    focus: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(user, db).teams(
        page=page,
        page_size=page_size,
        search=search,
        sort=sort,
        direction=direction if direction in {"asc", "desc"} else "asc",
        date_from=date_from,
        date_to=date_to,
        focus=focus,
    )


@router.get("/teams/{employee_id}")
def team_detail(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _service(user, db)
    detail = service.team_detail(employee_id)
    detail["turnaround_days"] = service.turnaround_days(employee_id)
    return detail


@router.get("/teams/{employee_id}/tasks")
def team_tasks(
    employee_id: int,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(user, db)
    service.scope.require_team(employee_id)
    from app.models.task import Task
    from app.models.team_lead import TeamLeadAssignment
    from app.services.activity_log import utc_today
    from app.services.oversight import _overdue

    members = db.query(TeamLeadAssignment.employee_id).filter(TeamLeadAssignment.team_lead_id == employee_id)
    query = db.query(Task).filter(Task.assigned_employee_id.in_(members))
    if status == "overdue":
        query = query.filter(_overdue())
    elif status == "open":
        query = query.filter(Task.status.notin_(("completed", "cancelled", "rejected")))
    elif status:
        query = query.filter(Task.status == status)
    if date_from:
        query = query.filter(Task.due_date >= date_from)
    if date_to:
        query = query.filter(Task.due_date <= date_to)
    total = query.count()
    rows = query.order_by(Task.due_date.asc(), Task.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "assignee_id": task.assigned_employee_id,
                "overdue": bool(task.due_date and task.due_date < utc_today() and task.status not in {"completed", "cancelled"}),
            }
            for task in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/teams/{employee_id}/reviews")
def team_reviews(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _service(user, db)
    service.scope.require_team(employee_id)
    from app.models.hr_evaluation import HREvaluation
    from app.models.task import Task
    from app.models.task_review import TaskReview
    from app.models.team_lead import TeamLeadAssignment
    from app.models.user import User as UserModel

    members = [row[0] for row in db.query(TeamLeadAssignment.employee_id).filter(TeamLeadAssignment.team_lead_id == employee_id).all()]
    lead_user = db.query(UserModel).filter(UserModel.employee_id == employee_id).first()
    task_rows = []
    evaluations = []
    if lead_user:
        task_rows = (
            db.query(TaskReview, Task)
            .join(Task, Task.id == TaskReview.task_id)
            .filter(TaskReview.reviewer_user_id == lead_user.id, Task.assigned_employee_id.in_(members or [-1]))
            .order_by(TaskReview.created_at.desc())
            .all()
        )
        evaluations = (
            db.query(HREvaluation)
            .filter(HREvaluation.evaluator_id == lead_user.id, HREvaluation.employee_id.in_(members or [-1]))
            .order_by(HREvaluation.created_at.desc())
            .all()
        )
    return {
        "tasks": [
            {"id": review.id, "task_id": task.id, "title": task.title, "status": review.status, "rating": review.rating, "comment": review.comments, "created_at": review.created_at.isoformat() + "Z"}
            for review, task in task_rows
        ],
        "performance": [
            {"id": item.id, "employee_id": item.employee_id, "score": item.score, "comment": item.comments, "period_end": item.period_end.isoformat(), "created_at": item.created_at.isoformat() + "Z"}
            for item in evaluations
        ],
    }


@router.get("/teams/{employee_id}/activity")
def team_activity(
    employee_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(user, db).activity(page=page, page_size=page_size, lead_only=employee_id)


@router.get("/employees/{employee_id}")
def employee_detail(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = _service(user, db)
    detail = service.employee_detail(employee_id)
    if service.scope.is_plain_employee():
        from app.models.activity_log import ActivityLog

        rows = (
            db.query(ActivityLog)
            .filter(ActivityLog.target_employee_id == employee_id)
            .order_by(ActivityLog.created_at.desc())
            .limit(50)
            .all()
        )
        detail["activity"] = {"items": [_activity_item(row) for row in rows], "total": len(rows), "page": 1, "page_size": 50}
    else:
        detail["activity"] = service.activity(page=1, page_size=50, employee_id=employee_id)
    return detail


@router.get("/hierarchy")
def hierarchy(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _service(user, db).hierarchy()


@router.get("/activity")
def activity(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    actor_id: int | None = None,
    team_lead_id: int | None = None,
    employee_id: int | None = None,
    action_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(user, db).activity(
        page=page,
        page_size=page_size,
        actor_id=actor_id,
        team_lead_id=team_lead_id,
        employee_id=employee_id,
        action_type=action_type,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/trends")
def trends(
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(user, db).trends(date_from, date_to)


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def _stream(headers: list[str], rows):
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([_csv_cell(cell) for cell in row])
            yield buffer.getvalue()

    return StreamingResponse(generate(), media_type="text/csv", headers={"Content-Disposition": "attachment"})


@router.get("/export/teams.csv")
def export_teams(
    search: str | None = None,
    sort: str = "name",
    direction: str = "asc",
    date_from: date | None = None,
    date_to: date | None = None,
    focus: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = _service(user, db).teams(page=1, page_size=100, search=search, sort=sort, direction=direction, date_from=date_from, date_to=date_to, focus=focus)
    items = list(payload["items"])
    page = 2
    while len(items) < payload["total"]:
        payload = _service(user, db).teams(page=page, page_size=100, search=search, sort=sort, direction=direction, date_from=date_from, date_to=date_to, focus=focus)
        items.extend(payload["items"])
        page += 1
        if page > 50:
            break
    rows = [
        [item["name"], item["job_title"], item["team_size"], item["open_tasks"], item["overdue_tasks"], item["on_time_rate"], item["pending_reviews"], item["average_rating"], item["last_activity"]]
        for item in payload["items"]
    ]
    return _stream(["Name", "Designation", "Team size", "Open", "Overdue", "On-time rate", "Pending reviews", "Average rating", "Last activity"], rows)


@router.get("/export/teams/{employee_id}/tasks.csv")
def export_team_tasks(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _service(user, db).scope.require_team(employee_id)

    def rows():
        session = SessionLocal()
        try:
            from app.models.task import Task
            from app.models.team_lead import TeamLeadAssignment

            members = session.query(TeamLeadAssignment.employee_id).filter(TeamLeadAssignment.team_lead_id == employee_id)
            query = session.query(Task).filter(Task.assigned_employee_id.in_(members)).yield_per(200)
            for task in query:
                yield [task.id, task.title, task.status, task.due_date.isoformat() if task.due_date else "", task.assigned_employee_id]
        finally:
            session.close()

    return _stream(["Id", "Title", "Status", "Due date", "Assignee id"], rows())


@router.get("/export/activity.csv")
def export_activity(
    actor_id: int | None = None,
    team_lead_id: int | None = None,
    employee_id: int | None = None,
    action_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(user, db)
    service.activity(page=1, page_size=1, actor_id=actor_id, team_lead_id=team_lead_id, employee_id=employee_id, action_type=action_type, date_from=date_from, date_to=date_to)
    user_id = user.id

    def rows():
        session = SessionLocal()
        try:
            fresh = session.get(User, user_id)
            scoped = OversightService(session, fresh)
            query = scoped._activity_query(actor_id, team_lead_id, employee_id, action_type, date_from, date_to, None)
            for row in query.order_by(row_order()).yield_per(200):
                item = _activity_item(row)
                yield [item["created_at"], item["sentence"], item["action_type"], "historical" if item["historical"] else ""]
        finally:
            session.close()

    from app.models.activity_log import ActivityLog

    def row_order():
        return ActivityLog.created_at.desc()

    return _stream(["When", "What happened", "Action", "Historical"], rows())
