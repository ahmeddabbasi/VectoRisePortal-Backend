from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user_id: int, title: str, message: str, notification_type: str = "system", link: str | None = None):
        note = Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
        )
        self.db.add(note)
        return note

    def list_for_user(self, user_id: int, unread_only: bool = False, limit: int = 50, days: int | None = None):
        q = self.db.query(Notification).filter(Notification.user_id == user_id)
        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            q = q.filter(Notification.created_at >= cutoff)
        if unread_only:
            q = q.filter(Notification.is_read.is_(False))
        return q.order_by(Notification.created_at.desc()).limit(limit).all()

    def unread_count(self, user_id: int, days: int | None = 3) -> int:
        q = self.db.query(func.count(Notification.id)).filter(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            q = q.filter(Notification.created_at >= cutoff)
        return int(q.scalar() or 0)

    def mark_read(self, notification_id: int, user_id: int):
        note = (
            self.db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if note:
            note.is_read = True
        return note

    def notify_admins(self, title: str, message: str, notification_type: str = "system", link: str | None = None):
        admins = self.db.query(User).filter(User.role == "admin", User.is_active.is_(True)).all()
        for admin in admins:
            self.create(admin.id, title, message, notification_type, link)

    def notify_employee(self, employee_id: int, title: str, message: str, notification_type: str = "system", link: str | None = None):
        user = self.db.query(User).filter(User.employee_id == employee_id).first()
        if user:
            self.create(user.id, title, message, notification_type, link)
