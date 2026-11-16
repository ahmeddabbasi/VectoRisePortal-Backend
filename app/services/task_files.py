import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, UploadFile
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.text_guard import image_extension, optional_text
from app.models.task_document import TaskDocument

RETENTION_DAYS = 4
_MAX_BYTES = 8 * 1024 * 1024
_DOC_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "txt": "text/plain",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def expiry_from(uploaded_at: datetime | None = None) -> datetime:
    return (uploaded_at or datetime.utcnow()) + timedelta(days=RETENTION_DAYS)


def purge_expired_task_documents(db: Session) -> int:
    now = datetime.utcnow()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    rows = (
        db.query(TaskDocument.id, TaskDocument.task_id, TaskDocument.original_name)
        .filter(
            or_(
                and_(TaskDocument.expires_at.is_not(None), TaskDocument.expires_at <= now),
                and_(TaskDocument.expires_at.is_(None), TaskDocument.created_at <= cutoff),
            )
        )
        .all()
    )
    if not rows:
        return 0
    from app.models.task import Task
    from app.services.activity_log import ActivityLogService

    log = ActivityLogService(db)
    ids = []
    for document_id, task_id, original_name in rows:
        task = db.get(Task, task_id)
        log.document_removed(task, document_id, original_name, "expired")
        ids.append(document_id)
    db.query(TaskDocument).filter(TaskDocument.id.in_(ids)).delete(synchronize_session=False)
    return len(ids)


def _kind(content: bytes, filename: str) -> str:
    lower = filename.lower()
    if content.startswith(b"%PDF") and lower.endswith(".pdf"):
        return "pdf"
    if content.startswith(b"PK\x03\x04") and lower.endswith(".docx"):
        return "docx"
    if content.startswith(b"\xd0\xcf\x11\xe0") and lower.endswith(".doc"):
        return "doc"
    if lower.endswith(".txt") and b"\x00" not in content[:4096]:
        return "txt"
    image = image_extension(content)
    if image and lower.endswith(image):
        return "jpg" if image in {".jpg", ".jpeg"} else image.lstrip(".")
    raise HTTPException(status_code=400, detail="Upload a PDF, Word document, text file, or image")


async def read_task_upload(task_id: int, upload: UploadFile) -> dict:
    content = await upload.read()
    if not content or len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="File must be between 1 byte and 8 MB")
    kind = _kind(content, upload.filename or "")
    original = optional_text(upload.filename, max_length=180) or f"document.{kind}"
    return {
        "content": content,
        "stored_name": f"{task_id}_{uuid.uuid4().hex}.{kind}",
        "original_name": original,
        "content_type": _DOC_TYPES[kind],
        "size_bytes": len(content),
        "expires_at": expiry_from(),
    }
