from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.activity import Activity
from app.models.data_source import DataSource
from app.models.employee import Employee
from app.models.lead import Lead
from app.models.sync_run import SyncRun
from app.models.target import Target
from app.models.user import User
from app.models.department import Department
from app.seed_config import DEFAULT_SOURCES, DEFAULT_TARGETS
from app.services.auth import hash_password
from app.services.normalize import row_to_lead_record
from app.services.settings_service import SettingsService
from app.services.sheets_client import GoogleSheetsClient, _resolve_credentials_path


def cleanup_stale_sync_runs(db: Session):
    stale = db.query(SyncRun).filter(SyncRun.status.in_(["running", "queued"])).all()
    for run in stale:
        run.status = "failed"
        run.message = "Sync interrupted — marked failed so a new sync can run"
        run.finished_at = datetime.utcnow()
    if stale:
        db.commit()


def seed_database(db: Session):
    if not db.query(Department).filter(Department.name == "Sales").first():
        db.add(Department(name="Sales", description="Sales and business development"))
    if not db.query(Department).filter(Department.name == "Operations").first():
        db.add(Department(name="Operations", description="Operations and workforce management"))
    db.flush()
    sales_dept = db.query(Department).filter(Department.name == "Sales").first()

    employee_seeds = [
        {"name": "Dawood", "email": "dawood@vectoriseinc.dev", "job_title": "Sales Executive"},
        {"name": "Hanya", "email": "hanya@vectoriseinc.dev", "job_title": "Sales Executive"},
    ]
    for idx, seed in enumerate(employee_seeds, start=1):
        employee = db.query(Employee).filter(Employee.name == seed["name"]).first()
        if not employee:
            employee = Employee(
                name=seed["name"],
                email=seed["email"],
                job_title=seed["job_title"],
                department_id=sales_dept.id if sales_dept else None,
                role="employee",
                employee_code=f"EMP{idx:04d}",
                joining_date=date.today(),
            )
            db.add(employee)
            db.flush()
        else:
            employee.email = employee.email or seed["email"]
            employee.job_title = employee.job_title or seed["job_title"]
            employee.employee_code = employee.employee_code or f"EMP{idx:04d}"
            if sales_dept and not employee.department_id:
                employee.department_id = sales_dept.id

        user = db.query(User).filter(User.email == seed["email"]).first()
        if not user:
            db.add(
                User(
                    email=seed["email"],
                    hashed_password=hash_password("employee123"),
                    role="employee",
                    employee_id=employee.id,
                )
            )
        elif not user.employee_id:
            user.employee_id = employee.id
            user.role = "employee"

    db.flush()
    employees = {e.name: e for e in db.query(Employee).all()}

    for src in DEFAULT_SOURCES:
        existing = (
            db.query(DataSource)
            .filter(DataSource.sheet_gid == src["sheet_gid"])
            .first()
        )
        if not existing:
            db.add(
                DataSource(
                    name=src["name"],
                    employee_name=src["employee_name"],
                    category=src["category"],
                    spreadsheet_id=settings.google_spreadsheet_id,
                    sheet_gid=src["sheet_gid"],
                    data_type=src["data_type"],
                )
            )

    for target in DEFAULT_TARGETS:
        employee = employees.get(target["employee_name"])
        if not employee:
            continue
        exists = (
            db.query(Target)
            .filter(
                Target.employee_id == employee.id,
                Target.activity_type == target["activity_type"],
                Target.period == target["period"],
            )
            .first()
        )
        if not exists:
            db.add(
                Target(
                    employee_id=employee.id,
                    activity_type=target["activity_type"],
                    target_value=target["target_value"],
                    period=target["period"],
                )
            )

    if not db.query(User).filter(User.email == settings.admin_email).first():
        db.add(
            User(
                email=settings.admin_email,
                hashed_password=hash_password(settings.admin_password),
                role="admin",
            )
        )

    SettingsService(db).seed_defaults()
    db.commit()


class SyncService:
    def __init__(self, db: Session):
        self.db = db
        self.client = GoogleSheetsClient()

    def _finalize(self, run_id: int, status: str, message: str, **fields) -> SyncRun:
        run = self.db.get(SyncRun, run_id)
        if not run:
            raise RuntimeError("Sync run record missing")
        run.status = status
        run.message = message
        run.finished_at = datetime.utcnow()
        for key, value in fields.items():
            setattr(run, key, value)
        self.db.commit()
        self.db.refresh(run)
        return run

    def run(self) -> SyncRun:
        cleanup_stale_sync_runs(self.db)

        run = SyncRun(status="running")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        run_id = run.id

        if not settings.google_spreadsheet_id:
            return self._finalize(run_id, "failed", "GOOGLE_SPREADSHEET_ID is not configured")

        try:
            _resolve_credentials_path()
        except FileNotFoundError as exc:
            return self._finalize(run_id, "failed", str(exc))

        leads_upserted = 0
        activities_upserted = 0
        rows_processed = 0
        errors: list[str] = []
        duplicate_map: dict[str, list[int]] = {}

        try:
            titles = self.client.get_sheet_titles(settings.google_spreadsheet_id)
            sources = db_sources(self.db)
            if not sources:
                return self._finalize(run_id, "failed", "No active sheet sources configured")

            for source in sources:
                try:
                    source_leads, source_rows, source_activities = self._sync_source(
                        source, titles, duplicate_map
                    )
                    leads_upserted += source_leads
                    rows_processed += source_rows
                    activities_upserted += source_activities
                    source.last_sync_at = datetime.utcnow()
                    source.last_sync_status = "success"
                    self.db.commit()
                except Exception as exc:
                    self.db.rollback()
                    errors.append(f"{source.name}: {exc}")

            mark_duplicates(self.db, duplicate_map)
            self.db.commit()

            if errors and not leads_upserted:
                return self._finalize(
                    run_id,
                    "failed",
                    "; ".join(errors[:3]),
                    rows_processed=rows_processed,
                    leads_upserted=leads_upserted,
                    activities_upserted=activities_upserted,
                )
            if errors:
                return self._finalize(
                    run_id,
                    "partial",
                    f"Synced {leads_upserted} leads with warnings: {'; '.join(errors[:2])}",
                    rows_processed=rows_processed,
                    leads_upserted=leads_upserted,
                    activities_upserted=activities_upserted,
                )
            return self._finalize(
                run_id,
                "success",
                f"Synced {leads_upserted} leads from {len(sources)} sources",
                rows_processed=rows_processed,
                leads_upserted=leads_upserted,
                activities_upserted=activities_upserted,
            )
        except Exception as exc:
            self.db.rollback()
            return self._finalize(
                run_id,
                "failed",
                str(exc),
                rows_processed=rows_processed,
                leads_upserted=leads_upserted,
                activities_upserted=activities_upserted,
            )

    def _sync_source(
        self,
        source: DataSource,
        titles: dict[int, str],
        duplicate_map: dict[str, list[int]],
    ) -> tuple[int, int, int]:
        title = titles.get(source.sheet_gid) or source.name
        source.sheet_title = title
        rows = self.client.fetch_sheet_rows(settings.google_spreadsheet_id, title)
        employee = (
            self.db.query(Employee)
            .filter(Employee.name == source.employee_name)
            .first()
        )
        if not employee:
            raise RuntimeError(f"Employee '{source.employee_name}' not found")

        leads_upserted = 0
        rows_processed = 0
        activities_upserted = 0

        for idx, row in enumerate(rows, start=2):
            record = row_to_lead_record(
                row,
                row_number=idx,
                source={
                    "name": source.name,
                    "category": source.category,
                    "sheet_gid": source.sheet_gid,
                    "sheet_title": title,
                    "data_type": source.data_type,
                },
                employee_id=employee.id,
                spreadsheet_id=settings.google_spreadsheet_id,
            )
            if not record:
                continue
            rows_processed += 1
            lead = (
                self.db.query(Lead)
                .filter(
                    Lead.source_gid == source.sheet_gid,
                    Lead.source_row == idx,
                )
                .first()
            )
            if not lead:
                lead = Lead(external_id=record["external_id"])
                self.db.add(lead)
            for field in [
                "external_id",
                "company_name",
                "contact_name",
                "email",
                "linkedin_url",
                "industry",
                "category",
                "employee_id",
                "current_stage",
                "reply_status",
                "meeting_status",
                "opportunity_status",
                "source_sheet",
                "source_sheet_id",
                "source_row",
                "source_gid",
                "last_activity_date",
                "next_follow_up_date",
            ]:
                setattr(lead, field, record[field])
            lead.synced_at = datetime.utcnow()
            lead.updated_at = datetime.utcnow()
            self.db.flush()
            leads_upserted += 1

            self.db.query(Activity).filter(Activity.lead_id == lead.id).delete(
                synchronize_session=False
            )
            for act in record["activities"]:
                self.db.add(
                    Activity(
                        lead_id=lead.id,
                        employee_id=employee.id,
                        activity_type=act["activity_type"],
                        activity_date=act.get("activity_date"),
                        source=title,
                    )
                )
                activities_upserted += 1

            dup_key = record.get("duplicate_key")
            if dup_key:
                duplicate_map.setdefault(dup_key, []).append(lead.id)

        return leads_upserted, rows_processed, activities_upserted


def db_sources(db: Session) -> list[DataSource]:
    sources = db.query(DataSource).filter(DataSource.is_active.is_(True)).all()
    if sources:
        return sources
    for src in DEFAULT_SOURCES:
        existing = db.query(DataSource).filter(DataSource.sheet_gid == src["sheet_gid"]).first()
        if not existing:
            db.add(
                DataSource(
                    name=src["name"],
                    employee_name=src["employee_name"],
                    category=src["category"],
                    spreadsheet_id=settings.google_spreadsheet_id,
                    sheet_gid=src["sheet_gid"],
                    data_type=src["data_type"],
                )
            )
    db.commit()
    return db.query(DataSource).filter(DataSource.is_active.is_(True)).all()


def mark_duplicates(db: Session, duplicate_map: dict[str, list[int]]):
    for lead in db.query(Lead).all():
        lead.is_duplicate = False
        lead.duplicate_group = None
    for key, lead_ids in duplicate_map.items():
        if len(lead_ids) < 2:
            continue
        for lead_id in lead_ids:
            lead = db.get(Lead, lead_id)
            if lead:
                lead.is_duplicate = True
                lead.duplicate_group = key
