from __future__ import annotations

from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import settings


def _resolve_credentials_path() -> Path:
    candidates = [
        Path(settings.google_service_account_path),
        Path(settings.google_service_account_path.replace("-", " ")),
        Path(__file__).resolve().parents[3] / "credentials" / "google-service-account.json",
        Path(__file__).resolve().parents[3] / "credentials" / "google service account.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("Google service account credentials not found")


class GoogleSheetsClient:
    def __init__(self):
        cred_path = _resolve_credentials_path()
        creds = service_account.Credentials.from_service_account_file(
            str(cred_path),
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def get_sheet_titles(self, spreadsheet_id: str) -> dict[int, str]:
        meta = (
            self.service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title,hidden))")
            .execute()
        )
        return {
            s["properties"]["sheetId"]: s["properties"]["title"]
            for s in meta.get("sheets", [])
            if not s["properties"].get("hidden")
        }

    def fetch_sheet_rows(self, spreadsheet_id: str, sheet_title: str) -> list[dict[str, str]]:
        escaped = sheet_title.replace("'", "''")
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{escaped}'!A:ZZ",
                majorDimension="ROWS",
            )
            .execute()
        )
        rows = result.get("values", [])
        if not rows:
            return []
        headers = [str(h).strip() for h in rows[0]]
        parsed: list[dict[str, str]] = []
        for row in rows[1:]:
            if not any(str(c).strip() for c in row):
                continue
            item = {}
            for i, header in enumerate(headers):
                if not header:
                    continue
                item[header] = str(row[i]).strip() if i < len(row) else ""
            parsed.append(item)
        return parsed
