from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.hrm import NotificationOut
from app.services.notifications import NotificationService

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(days: int = 3, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return NotificationService(db).list_for_user(user.id, days=days)


@router.get("/unread-count")
def notification_unread_count(days: int = 3, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"count": NotificationService(db).unread_count(user.id, days=days)}


@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    NotificationService(db).mark_read(notification_id, user.id)
    db.commit()
    return {"status": "ok"}
