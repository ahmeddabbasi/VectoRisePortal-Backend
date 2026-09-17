import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: str,
        user: User | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        previous: Any = None,
        new: Any = None,
        reason: str | None = None,
        ip_address: str | None = None,
    ):
        entry = AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_value=json.dumps(previous) if previous is not None else None,
            new_value=json.dumps(new) if new is not None else None,
            reason=reason,
            ip_address=ip_address,
        )
        self.db.add(entry)
        return entry
