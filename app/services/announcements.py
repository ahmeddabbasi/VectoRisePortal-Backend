from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.announcement import Announcement
from app.models.user import User
from app.services.audit import AuditService
from app.services.notifications import NotificationService


class AnnouncementService:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self, limit: int = 50) -> list[Announcement]:
        return (
            self.db.query(Announcement)
            .order_by(Announcement.created_at.desc())
            .limit(limit)
            .all()
        )

    def broadcast(self, admin: User, title: str, body: str) -> Announcement:
        title = title.strip()
        body = body.strip()
        if not title or not body:
            raise HTTPException(status_code=400, detail="Title and message are required")

        ann = Announcement(title=title, body=body, created_by_user_id=admin.id)
        self.db.add(ann)
        self.db.flush()

        employees = (
            self.db.query(User)
            .filter(User.role == "employee", User.is_active.is_(True))
            .all()
        )
        notifier = NotificationService(self.db)
        for user in employees:
            notifier.create(
                user.id,
                title=title,
                message=body,
                notification_type="announcement",
                link="/employee/chat",
            )

        AuditService(self.db).log(
            action="announcement.broadcast",
            user=admin,
            entity_type="announcement",
            entity_id=ann.id,
            new={"title": title, "recipients": len(employees)},
        )
        return ann
