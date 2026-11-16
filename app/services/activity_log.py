"""Append-only work history. Callers commit; this service only flushes."""

from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.employee import Employee
from app.models.user import User

ACTIVE_WINDOW = timedelta(minutes=15)

CLOSED_STATUSES = ("completed", "cancelled")
TERMINAL_STATUSES = ("completed", "cancelled", "rejected")


def utcnow() -> datetime:
    return datetime.utcnow()


def utc_today():
    return utcnow().date()


class ActivityLogService:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        *,
        action_type: str,
        entity_type: str,
        entity_id: int | None,
        actor_id: int | None = None,
        target_employee_id: int | None = None,
        team_lead_id: int | None = None,
        metadata: dict | None = None,
        backfill_key: str | None = None,
        created_at: datetime | None = None,
    ) -> ActivityLog | None:
        if backfill_key:
            existing = self.db.query(ActivityLog.id).filter(ActivityLog.backfill_key == backfill_key).first()
            if existing:
                return None
        row = ActivityLog(
            actor_id=actor_id,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            target_employee_id=target_employee_id,
            team_lead_id=team_lead_id,
            metadata_json=metadata or {},
            created_at=created_at or utcnow(),
            backfill_key=backfill_key,
        )
        self.db.add(row)
        if not backfill_key:
            self.db.flush()
            return row
        nested = self.db.begin_nested()
        try:
            self.db.flush()
        except IntegrityError:
            nested.rollback()
            return None
        return row

    def touch_last_active(self, user: User, now: datetime | None = None) -> bool:
        now = now or utcnow()
        if user.last_active_at and now - user.last_active_at < ACTIVE_WINDOW:
            return False
        user.last_active_at = now
        self.db.commit()
        return True

    def login(self, user: User, now: datetime | None = None) -> None:
        now = now or utcnow()
        user.last_active_at = now
        employee = self.db.get(Employee, user.employee_id) if user.employee_id else None
        self.record(
            action_type="login",
            entity_type="user",
            entity_id=user.id,
            actor_id=user.id,
            target_employee_id=user.employee_id,
            metadata={"actor_name": employee.name if employee else user.email, "backfilled": False},
            created_at=now,
        )

    def team_assigned(self, actor: User | None, team_lead_id: int, employee_id: int, assignment_id: int) -> None:
        lead = self.db.get(Employee, team_lead_id)
        member = self.db.get(Employee, employee_id)
        self.record(
            action_type="team_lead_assigned",
            entity_type="team_lead_assignment",
            entity_id=assignment_id,
            actor_id=actor.id if actor else None,
            target_employee_id=employee_id,
            team_lead_id=team_lead_id,
            metadata={
                "actor_name": _actor_name(actor, self.db),
                "lead_name": lead.name if lead else "Team lead",
                "target_name": member.name if member else "Employee",
                "backfilled": False,
            },
        )

    def team_removed(self, actor: User | None, team_lead_id: int, employee_id: int, assignment_id: int | None) -> None:
        lead = self.db.get(Employee, team_lead_id)
        member = self.db.get(Employee, employee_id)
        self.record(
            action_type="team_lead_removed",
            entity_type="team_lead_assignment",
            entity_id=assignment_id,
            actor_id=actor.id if actor else None,
            target_employee_id=employee_id,
            team_lead_id=team_lead_id,
            metadata={
                "actor_name": _actor_name(actor, self.db),
                "lead_name": lead.name if lead else "Team lead",
                "target_name": member.name if member else "Employee",
                "backfilled": False,
            },
        )

    def task_created(self, actor: User | None, task) -> None:
        self.record(
            action_type="task_created",
            entity_type="task",
            entity_id=task.id,
            actor_id=actor.id if actor else None,
            target_employee_id=task.assigned_employee_id,
            team_lead_id=_lead_context(self.db, actor, task.assigned_employee_id),
            metadata=_task_meta(self.db, actor, task),
        )

    def task_changes(self, actor: User | None, task, before: dict) -> None:
        lead_id = _lead_context(self.db, actor, task.assigned_employee_id)
        base = _task_meta(self.db, actor, task)
        old_status = str(before.get("status") or "")
        new_status = str(task.status or "")
        if old_status != new_status:
            action = "task_completed" if new_status == "completed" else "task_status_changed"
            self.record(
                action_type=action,
                entity_type="task",
                entity_id=task.id,
                actor_id=actor.id if actor else None,
                target_employee_id=task.assigned_employee_id,
                team_lead_id=lead_id,
                metadata={**base, "old_status": old_status, "new_status": new_status},
            )
        old_due = before.get("due_date")
        if "due_date" in before and old_due != task.due_date:
            self.record(
                action_type="task_deadline_changed",
                entity_type="task",
                entity_id=task.id,
                actor_id=actor.id if actor else None,
                target_employee_id=task.assigned_employee_id,
                team_lead_id=lead_id,
                metadata={**base, "old_due_date": _iso(old_due), "new_due_date": _iso(task.due_date)},
            )
        if before.get("notes") != task.notes:
            self.record(
                action_type="task_note_changed",
                entity_type="task",
                entity_id=task.id,
                actor_id=actor.id if actor else None,
                target_employee_id=task.assigned_employee_id,
                team_lead_id=lead_id,
                metadata={**base, "old_notes": before.get("notes") or "", "new_notes": task.notes or ""},
            )

    def document_uploaded(self, actor: User, task, document) -> None:
        meta = _task_meta(self.db, actor, task)
        meta["file_name"] = document.original_name
        self.record(
            action_type="document_uploaded",
            entity_type="task_document",
            entity_id=document.id,
            actor_id=actor.id,
            target_employee_id=task.assigned_employee_id,
            team_lead_id=_lead_context(self.db, actor, task.assigned_employee_id),
            metadata=meta,
        )

    def document_removed(self, task, document_id: int, file_name: str, reason: str) -> None:
        target = task.assigned_employee_id if task else None
        self.record(
            action_type="document_removed",
            entity_type="task_document",
            entity_id=document_id,
            actor_id=None,
            target_employee_id=target,
            metadata={
                "actor_name": "System",
                "title": task.title if task else "Task",
                "target_name": _employee_name(self.db, target),
                "file_name": file_name,
                "reason": reason,
                "backfilled": False,
            },
        )

    def task_review(self, actor: User, task, review) -> None:
        meta = _task_meta(self.db, actor, task)
        meta.update({"status": review.status, "rating": review.rating, "comment": review.comments or ""})
        self.record(
            action_type="task_review_submitted",
            entity_type="task_review",
            entity_id=review.id,
            actor_id=actor.id,
            target_employee_id=task.assigned_employee_id,
            team_lead_id=_lead_context(self.db, actor, task.assigned_employee_id),
            metadata=meta,
        )

    def performance_review(self, actor: User, evaluation) -> None:
        self.record(
            action_type="performance_review_submitted",
            entity_type="hr_evaluation",
            entity_id=evaluation.id,
            actor_id=actor.id,
            target_employee_id=evaluation.employee_id,
            team_lead_id=_lead_context(self.db, actor, evaluation.employee_id),
            metadata={
                "actor_name": _actor_name(actor, self.db),
                "target_name": _employee_name(self.db, evaluation.employee_id),
                "score": evaluation.score,
                "comment": evaluation.comments or "",
                "period_start": _iso(evaluation.period_start),
                "period_end": _iso(evaluation.period_end),
                "backfilled": False,
            },
        )


def describe(row: ActivityLog) -> str:
    meta = row.metadata_json or {}
    actor = meta.get("actor_name") or "Someone"
    target = meta.get("target_name") or "an employee"
    title = meta.get("title") or "a task"
    kind = row.action_type
    if kind == "team_lead_assigned":
        return f"{actor} made {meta.get('lead_name') or 'a team lead'} the team lead of {target}"
    if kind == "team_lead_removed":
        return f"{actor} removed {meta.get('lead_name') or 'a team lead'} as team lead of {target}"
    if kind == "task_created":
        return f"{actor} assigned '{title}' to {target}"
    if kind == "task_completed":
        return f"{actor} completed '{title}'"
    if kind == "task_status_changed":
        return f"{actor} changed '{title}' from {meta.get('old_status') or 'unknown'} to {meta.get('new_status') or 'unknown'}"
    if kind == "task_deadline_changed":
        return f"{actor} changed the deadline for '{title}' from {meta.get('old_due_date') or 'none'} to {meta.get('new_due_date') or 'none'}"
    if kind == "task_note_changed":
        return f"{actor} updated the notes on '{title}'"
    if kind == "document_uploaded":
        return f"{actor} uploaded {meta.get('file_name') or 'a file'} for '{title}'"
    if kind == "document_removed":
        return f"{actor} removed {meta.get('file_name') or 'a file'} from '{title}'"
    if kind == "task_review_submitted":
        rating = meta.get("rating")
        rated = f", rated {rating}" if rating is not None else ""
        return f"{actor} reviewed '{title}' as {meta.get('status') or 'reviewed'}{rated}"
    if kind == "performance_review_submitted":
        return f"{actor} submitted a performance review for {target}"
    if kind == "login":
        return f"{actor} signed in"
    return f"{actor} recorded {kind.replace('_', ' ')}"


def _actor_name(actor: User | None, db: Session) -> str:
    if not actor:
        return "System"
    if actor.employee_id:
        employee = db.get(Employee, actor.employee_id)
        if employee:
            return employee.name
    return actor.email


def _employee_name(db: Session, employee_id: int | None) -> str:
    if not employee_id:
        return "an employee"
    employee = db.get(Employee, employee_id)
    return employee.name if employee else "an employee"


def _lead_context(db: Session, actor: User | None, target_employee_id: int | None) -> int | None:
    if not actor or not actor.employee_id or not target_employee_id:
        return None
    from app.models.team_lead import TeamLeadAssignment

    row = (
        db.query(TeamLeadAssignment.id)
        .filter(
            TeamLeadAssignment.team_lead_id == actor.employee_id,
            TeamLeadAssignment.employee_id == target_employee_id,
        )
        .first()
    )
    return actor.employee_id if row else None


def _task_meta(db: Session, actor: User | None, task) -> dict:
    return {
        "actor_name": _actor_name(actor, db),
        "target_name": _employee_name(db, task.assigned_employee_id),
        "title": task.title,
        "task_id": task.id,
        "backfilled": False,
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def run_backfill(db: Session) -> int:
    from app.models.hr_evaluation import HREvaluation
    from app.models.system_setting import SystemSetting
    from app.models.task import Task
    from app.models.task_document import TaskDocument
    from app.models.task_review import TaskReview
    from app.models.team_lead import TeamLeadAssignment
    from app.models.user import User as UserModel

    if not db.query(SystemSetting).filter(SystemSetting.key == "oversight_launch_at").first():
        db.add(
            SystemSetting(
                key="oversight_launch_at",
                value=utcnow().replace(microsecond=0).isoformat() + "Z",
                description="When team oversight started recording live history",
            )
        )
        db.flush()

    service = ActivityLogService(db)
    written = 0
    users = {row.id: row for row in db.query(UserModel).all()}
    employees = {row.id: row for row in db.query(Employee).all()}

    def actor_for(user_id: int | None) -> UserModel | None:
        return users.get(user_id) if user_id else None

    for task in db.query(Task).all():
        actor = actor_for(task.assigned_by_id)
        row = service.record(
            action_type="task_created",
            entity_type="task",
            entity_id=task.id,
            actor_id=task.assigned_by_id,
            target_employee_id=task.assigned_employee_id,
            team_lead_id=_lead_context(db, actor, task.assigned_employee_id),
            metadata={
                "actor_name": _actor_name(actor, db),
                "target_name": employees[task.assigned_employee_id].name if task.assigned_employee_id in employees else "Employee",
                "title": task.title,
                "task_id": task.id,
                "backfilled": True,
            },
            backfill_key=f"task:{task.id}",
            created_at=task.created_at,
        )
        written += int(row is not None)

    for assignment in db.query(TeamLeadAssignment).all():
        actor = actor_for(assignment.created_by)
        lead = employees.get(assignment.team_lead_id)
        member = employees.get(assignment.employee_id)
        row = service.record(
            action_type="team_lead_assigned",
            entity_type="team_lead_assignment",
            entity_id=assignment.id,
            actor_id=assignment.created_by,
            target_employee_id=assignment.employee_id,
            team_lead_id=assignment.team_lead_id,
            metadata={
                "actor_name": _actor_name(actor, db),
                "lead_name": lead.name if lead else "Team lead",
                "target_name": member.name if member else "Employee",
                "backfilled": True,
            },
            backfill_key=f"assignment:{assignment.id}",
            created_at=assignment.created_at,
        )
        written += int(row is not None)

    for review in db.query(TaskReview).all():
        from app.models.task import Task as TaskModel

        task = db.get(TaskModel, review.task_id)
        if not task:
            continue
        actor = actor_for(review.reviewer_user_id)
        row = service.record(
            action_type="task_review_submitted",
            entity_type="task_review",
            entity_id=review.id,
            actor_id=review.reviewer_user_id,
            target_employee_id=task.assigned_employee_id,
            team_lead_id=_lead_context(db, actor, task.assigned_employee_id),
            metadata={
                "actor_name": _actor_name(actor, db),
                "target_name": employees[task.assigned_employee_id].name if task.assigned_employee_id in employees else "Employee",
                "title": task.title,
                "task_id": task.id,
                "status": review.status,
                "rating": review.rating,
                "comment": review.comments or "",
                "backfilled": True,
            },
            backfill_key=f"task_review:{review.id}",
            created_at=review.created_at,
        )
        written += int(row is not None)

    for evaluation in db.query(HREvaluation).all():
        actor = actor_for(evaluation.evaluator_id)
        row = service.record(
            action_type="performance_review_submitted",
            entity_type="hr_evaluation",
            entity_id=evaluation.id,
            actor_id=evaluation.evaluator_id,
            target_employee_id=evaluation.employee_id,
            team_lead_id=_lead_context(db, actor, evaluation.employee_id),
            metadata={
                "actor_name": _actor_name(actor, db),
                "target_name": employees[evaluation.employee_id].name if evaluation.employee_id in employees else "Employee",
                "score": evaluation.score,
                "comment": evaluation.comments or "",
                "backfilled": True,
            },
            backfill_key=f"evaluation:{evaluation.id}",
            created_at=evaluation.created_at,
        )
        written += int(row is not None)

    now = utcnow()
    for document in db.query(TaskDocument).filter((TaskDocument.expires_at.is_(None)) | (TaskDocument.expires_at > now)).all():
        from app.models.task import Task as TaskModel

        task = db.get(TaskModel, document.task_id)
        if not task:
            continue
        actor = actor_for(document.uploaded_by_user_id)
        row = service.record(
            action_type="document_uploaded",
            entity_type="task_document",
            entity_id=document.id,
            actor_id=document.uploaded_by_user_id,
            target_employee_id=task.assigned_employee_id,
            team_lead_id=_lead_context(db, actor, task.assigned_employee_id),
            metadata={
                "actor_name": _actor_name(actor, db),
                "target_name": employees[task.assigned_employee_id].name if task.assigned_employee_id in employees else "Employee",
                "title": task.title,
                "task_id": task.id,
                "file_name": document.original_name,
                "backfilled": True,
            },
            backfill_key=f"document:{document.id}",
            created_at=document.created_at,
        )
        written += int(row is not None)
    return written
