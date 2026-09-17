"""Cloud bootstrap helpers — write secrets to disk when only env vars are available."""

import json
import os
from pathlib import Path

from app.config import CREDENTIALS_DIR, settings


def ensure_google_credentials() -> None:
    """If GOOGLE_SERVICE_ACCOUNT_JSON is set, write it to the credentials path."""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    target = Path(settings.google_service_account_path)
    if target.exists():
        return
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must be valid JSON")
    target.write_text(json.dumps(parsed), encoding="utf-8")
