from datetime import datetime

from sqlalchemy.orm import Session

from app.models.exception_record import ExceptionRecord
from app.models.user import User
from app.services.audit import AuditService


class ExceptionService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def create(
        self,
        employee_id: int,
        exception_type: str,
        title: str,
        description: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: int | None = None,
        occurred_at: datetime | None = None,
    ) -> ExceptionRecord:
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
        return record

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
