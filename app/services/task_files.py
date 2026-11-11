import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.core.text_guard import image_extension, optional_text

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
_MAX_BYTES = 8 * 1024 * 1024


def task_upload_dir() -> Path:
    path = settings.upload_path / "tasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


async def store_task_file(task_id: int, upload: UploadFile) -> tuple[str, str, str, int]:
    content = await upload.read()
    if not content or len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="File must be between 1 byte and 8 MB")
    kind = _kind(content, upload.filename or "")
    stored = f"{task_id}_{uuid.uuid4().hex}.{kind}"
    (task_upload_dir() / stored).write_bytes(content)
    original = optional_text(upload.filename, max_length=180) or f"document.{kind}"
    return stored, original, _DOC_TYPES[kind], len(content)
