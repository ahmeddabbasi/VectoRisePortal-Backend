"""Treat user text as data.

Stored text is never a system instruction. Callers must not concatenate the
result into a model prompt, SQL string, file path, or HTML sink.
"""

import re

_CONTROL_TOKENS = (
    "<|im_start|>",
    "<|im_end|>",
    "<|system|>",
    "<|user|>",
    "<|assistant|>",
    "<<SYS>>",
    "<</SYS>>",
    "[INST]",
    "[/INST]",
    "</s>",
    "<s>",
)
_TAG = re.compile(r"<[^>\n]{0,200}>")
_HIDDEN = re.compile(
    r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f"
    r"\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^[0-9+\-(). ]{7,30}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAYS = re.compile(r"^([0-6])(,[0-6])*$")
PROFILE_FILE = re.compile(r"^[0-9]+_[a-f0-9]{32}\.(jpg|jpeg|png|webp|gif)$")

ROLES = {"admin", "employee"}
EMPLOYEE_STATUSES = {"active", "inactive"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}
TASK_STATUSES = {
    "pending_approval",
    "not_started",
    "in_progress",
    "blocked",
    "completed",
    "overdue",
    "rejected",
    "cancelled",
}
EMPLOYEE_TASK_STATUSES = {"not_started", "in_progress", "blocked", "completed"}
EXCEPTION_REVIEW = {"under_review", "approved", "rejected", "resolved"}
SCHEDULE_REVIEW = {"approved", "rejected"}
ATTENDANCE_STATUSES = {"on_time", "late", "early", "absent", "incomplete", "on_leave"}


def sanitize_untrusted(value: str, *, max_length: int, allow_newlines: bool = True) -> str:
    text = _HIDDEN.sub("", value)
    lowered_tokens = {token.lower() for token in _CONTROL_TOKENS}
    # Remove model control tokens without treating the rest of the sentence as code.
    for token in list(_CONTROL_TOKENS) + [token.lower() for token in _CONTROL_TOKENS]:
        if token.lower() in lowered_tokens:
            text = text.replace(token, "")
    text = _TAG.sub("", text)
    if allow_newlines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{4,}", "\n\n\n", text)
    else:
        text = " ".join(text.split())
    text = text.strip()
    if len(text) > max_length:
        raise ValueError(f"Must be {max_length} characters or fewer")
    return text


def require_text(value: str, *, max_length: int, allow_newlines: bool = True) -> str:
    cleaned = sanitize_untrusted(value, max_length=max_length, allow_newlines=allow_newlines)
    if not cleaned:
        raise ValueError("This field cannot be empty")
    return cleaned


def optional_text(value: str | None, *, max_length: int, allow_newlines: bool = True) -> str | None:
    if value is None:
        return None
    cleaned = sanitize_untrusted(value, max_length=max_length, allow_newlines=allow_newlines)
    return cleaned or None


def normalize_email(value: str) -> str:
    email = sanitize_untrusted(value, max_length=255, allow_newlines=False).lower()
    if not _EMAIL.match(email):
        raise ValueError("Enter a valid email address")
    return email


def validate_password(value: str) -> str:
    if not isinstance(value, str) or len(value) < 8 or len(value) > 128:
        raise ValueError("Password must be 8 to 128 characters")
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        raise ValueError("Password must include a letter and a number")
    return value


def validate_phone(value: str | None) -> str | None:
    if value is None:
        return None
    phone = sanitize_untrusted(value, max_length=30, allow_newlines=False)
    if not phone:
        return None
    if not _PHONE.match(phone):
        raise ValueError("Enter a valid phone number")
    return phone


def one_of(value: str | None, allowed: set[str]) -> str | None:
    if value is None:
        return None
    if value not in allowed:
        raise ValueError("Unsupported value")
    return value


def image_extension(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    return None


def valid_clock(value: str) -> bool:
    return bool(_TIME.match(value))


def valid_working_days(value: str) -> bool:
    if not _DAYS.match(value):
        return False
    parts = value.split(",")
    return len(parts) == len(set(parts))
