from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.exception_record import ExceptionRecord
from app.models.user import User
from app.services.audit import AuditService
from app.services.notifications import NotificationService

OPEN_STATUSES = ("open", "under_review")


@dataclass
class ExceptionCreateResult:
    record: ExceptionRecord
    created: bool


class ExceptionService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        self.notifications = NotificationService(db)

    def _find_open_duplicate(
        self,
        employee_id: int,
        exception_type: str,
        related_entity_type: str | None = None,
        related_entity_id: int | None = None,
    ) -> ExceptionRecord | None:
        q = self.db.query(ExceptionRecord).filter(
            ExceptionRecord.employee_id == employee_id,
            ExceptionRecord.exception_type == str(exception_type),
            ExceptionRecord.status.in_(OPEN_STATUSES),
        )
        if related_entity_type is not None:
            q = q.filter(ExceptionRecord.related_entity_type == related_entity_type)
        else:
            q = q.filter(ExceptionRecord.related_entity_type.is_(None))
        if related_entity_id is not None:
            q = q.filter(ExceptionRecord.related_entity_id == related_entity_id)
        else:
            q = q.filter(ExceptionRecord.related_entity_id.is_(None))
        return q.order_by(ExceptionRecord.created_at.desc()).first()

    def _notify_admins(self, record: ExceptionRecord) -> None:
        employee = self.db.get(Employee, record.employee_id)
        name = employee.name if employee else f"Employee #{record.employee_id}"
        self.notifications.notify_admins(
            f"New exception: {record.title}",
            f"{name} — {record.description or record.title}",
            "exception",
            "/admin/exceptions",
        )

    def create(
        self,
        employee_id: int,
        exception_type: str,
        title: str,
        description: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: int | None = None,
        occurred_at: datetime | None = None,
        notify_admins: bool = True,
    ) -> ExceptionCreateResult:
        existing = self._find_open_duplicate(
            employee_id,
            exception_type,
            related_entity_type,
            related_entity_id,
        )
        if existing:
            return ExceptionCreateResult(record=existing, created=False)

        record = ExceptionRecord(
            employee_id=employee_id,
            exception_type=str(exception_type),
            title=title,
            description=description,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            occurred_at=occurred_at or datetime.utcnow(),
        )
        self.db.add(record)
        self.db.flush()
        if notify_admins:
            self._notify_admins(record)
        return ExceptionCreateResult(record=record, created=True)

    def resolve(self, exception_id: int, admin: User, status: str, admin_response: str | None = None):
        record = self.db.get(ExceptionRecord, exception_id)
        if not record:
            return None
        previous = {"status": record.status}
        record.status = status
        record.admin_response = admin_response
        record.resolved_by = admin.id
        record.resolved_at = datetime.utcnow()
        self.audit.log("exception_resolved", admin, "exception", record.id, previous, {"status": status}, admin_response)
        return record

    def list_exceptions(self, employee_id: int | None = None, status: str | None = None, limit: int = 100):
        q = self.db.query(ExceptionRecord)
        if employee_id:
            q = q.filter(ExceptionRecord.employee_id == employee_id)
        if status:
            q = q.filter(ExceptionRecord.status == status)
        return q.order_by(ExceptionRecord.created_at.desc()).limit(limit).all()
