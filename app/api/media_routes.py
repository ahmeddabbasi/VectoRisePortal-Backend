import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, undefer

from app.config import settings
from app.core.deps import get_current_user
from app.core.text_guard import PROFILE_FILE
from app.database import get_db
from app.models.enums import UserRole
from app.models.task import Task
from app.models.task_document import TaskDocument
from app.models.user import User
from app.services.task_files import purge_expired_task_documents

router = APIRouter(prefix="/api/media", tags=["media"])

_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_TASK_FILE = re.compile(r"^\d+_[0-9a-f]{32}\.(pdf|docx|doc|txt|png|jpg|jpeg|gif|webp)$")
_TASK_TYPES = {
    **_TYPES,
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


@router.get("/profile/{filename}")
def profile_photo(filename: str, user: User = Depends(get_current_user)):
    if not PROFILE_FILE.match(filename):
        raise HTTPException(status_code=404, detail="Not found")

    owner_id = int(filename.split("_", 1)[0])
    if user.role != UserRole.ADMIN and user.employee_id != owner_id:
        raise HTTPException(status_code=404, detail="Not found")

    root = (settings.upload_path / "profile").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(
        path,
        media_type=_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/tasks/{filename}")
def task_document(filename: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not _TASK_FILE.match(filename):
        raise HTTPException(status_code=404, detail="Not found")

    if purge_expired_task_documents(db):
        db.commit()
    doc = (
        db.query(TaskDocument)
        .options(undefer(TaskDocument.content))
        .filter(TaskDocument.stored_name == filename)
        .first()
    )
    if not doc or not doc.content:
        raise HTTPException(status_code=404, detail="Not found")
    task = db.get(Task, doc.task_id)
    allowed = user.role == UserRole.ADMIN or user.can_review_tasks or (task and user.employee_id == task.employee_id)
    if not allowed:
        raise HTTPException(status_code=404, detail="Not found")

    download_name = _SAFE_NAME.sub("", doc.original_name).strip() or filename
    return Response(
        content=bytes(doc.content),
        media_type=doc.content_type or _TASK_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
