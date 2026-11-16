"""Notify admins once per oversight episode. A cleared row can alert again later."""

from datetime import timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.employee import Employee
from app.models.oversight_alert import OversightAlert
from app.models.task import Task
from app.models.task_review import TaskReview
from app.models.team_lead import TeamLeadAssignment
from app.models.user import User
from app.services.activity_log import CLOSED_STATUSES, utc_today, utcnow
from app.services.notifications import NotificationService
from app.services.oversight import _overdue, _settings


def run_oversight_alerts(db: Session) -> int:
    thresholds = _settings(db)
    notes = NotificationService(db)
    sent = 0
    today = utc_today()
    now = utcnow()
    overdue_before = today - timedelta(days=thresholds["task_overdue_days"])
    review_before = now - timedelta(days=thresholds["review_pending_days"])
    inactive_before = now - timedelta(days=thresholds["inactive_days"])

    overdue_ids = set()
    for task in db.query(Task).filter(Task.due_date.isnot(None), Task.due_date < overdue_before, Task.status.notin_(CLOSED_STATUSES)).all():
        overdue_ids.add(task.id)
        if _open_alert(db, "task_overdue", "task", task.id):
            continue
        notes.notify_admins(
            "Task overdue",
            f"{task.title} is more than {thresholds['task_overdue_days']} day(s) past its due date.",
            "task",
            "/admin/oversight",
        )
        _open(db, "task_overdue", "task", task.id)
        sent += 1
    _clear_missing(db, "task_overdue", "task", overdue_ids)

    reviewed = {row[0] for row in db.query(TaskReview.task_id).all()}
    pending_ids = set()
    pending = db.query(Task).filter(Task.status == "completed", Task.completed_at.isnot(None), Task.completed_at < review_before).all()
    for task in pending:
        if task.id in reviewed:
            continue
        pending_ids.add(task.id)
        if _open_alert(db, "review_pending", "task", task.id):
            continue
        notes.notify_admins(
            "Review still waiting",
            f"{task.title} has been completed for more than {thresholds['review_pending_days']} day(s) without a review.",
            "task",
            "/admin/oversight",
        )
        _open(db, "review_pending", "task", task.id)
        sent += 1
    _clear_missing(db, "review_pending", "task", pending_ids)

    inactive_ids = set()
    lead_ids = [row[0] for row in db.query(TeamLeadAssignment.team_lead_id).distinct().all()]
    for lead_id in lead_ids:
        user = db.query(User).filter(User.employee_id == lead_id).first()
        last_active = user.last_active_at if user else None
        log_at = db.query(func.max(ActivityLog.created_at)).filter(
            or_(ActivityLog.team_lead_id == lead_id, ActivityLog.actor_id == (user.id if user else -1))
        ).scalar()
        latest = max((value for value in (last_active, log_at) if value), default=None)
        if latest and latest >= inactive_before:
            continue
        inactive_ids.add(lead_id)
        if _open_alert(db, "lead_inactive", "employee", lead_id):
            continue
        lead = db.get(Employee, lead_id)
        notes.notify_admins(
            "Team lead inactive",
            f"{lead.name if lead else 'A team lead'} has had no activity for more than {thresholds['inactive_days']} day(s).",
            "system",
            f"/admin/oversight/teams/{lead_id}",
        )
        _open(db, "lead_inactive", "employee", lead_id)
        sent += 1
    _clear_missing(db, "lead_inactive", "employee", inactive_ids)

    assigned = {row[0] for row in db.query(TeamLeadAssignment.employee_id).all()}
    unassigned_ids = set()
    for employee in db.query(Employee).filter(Employee.status == "active").all():
        if employee.id in assigned:
            continue
        unassigned_ids.add(employee.id)
        if _open_alert(db, "employee_unassigned", "employee", employee.id):
            continue
        notes.notify_admins(
            "Employee has no team lead",
            f"{employee.name} does not have a team lead.",
            "system",
            "/admin/oversight?focus=unassigned",
        )
        _open(db, "employee_unassigned", "employee", employee.id)
        sent += 1
    _clear_missing(db, "employee_unassigned", "employee", unassigned_ids)
    return sent


def _open_alert(db: Session, kind: str, entity_type: str, entity_id: int) -> bool:
    return (
        db.query(OversightAlert.id)
        .filter(
            OversightAlert.kind == kind,
            OversightAlert.entity_type == entity_type,
            OversightAlert.entity_id == entity_id,
            OversightAlert.cleared_at.is_(None),
        )
        .first()
        is not None
    )


def _open(db: Session, kind: str, entity_type: str, entity_id: int) -> None:
    db.add(OversightAlert(kind=kind, entity_type=entity_type, entity_id=entity_id, notified_at=utcnow()))


def _clear_missing(db: Session, kind: str, entity_type: str, current_ids: set[int]) -> None:
    rows = (
        db.query(OversightAlert)
        .filter(OversightAlert.kind == kind, OversightAlert.entity_type == entity_type, OversightAlert.cleared_at.is_(None))
        .all()
    )
    now = utcnow()
    for row in rows:
        if row.entity_id not in current_ids:
            row.cleared_at = now
