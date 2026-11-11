from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import require_admin, require_sales_access
from app.database import get_db
from app.models.activity import Activity
from app.models.data_source import DataSource
from app.models.employee import Employee
from app.models.lead import Lead
from app.models.sync_run import SyncRun
from app.models.user import User
from app.schemas.common import (
    ActivityResponse,
    DataSourceResponse,
    EmployeeResponse,
    LeadDetailResponse,
    LeadResponse,
    SyncStatusResponse,
)
from app.services.metrics import MetricsService
from app.services.sync import SyncService, cleanup_stale_sync_runs
from app.services.sync_jobs import is_sync_running, start_background_sync

router = APIRouter(prefix="/api", tags=["sales"])


@router.get("/dashboard/overview")
def dashboard_overview(
    period: str = Query("this_month"),
    employee: str | None = Query(None),
    category: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    return MetricsService(db).overview(period, employee, category, start_date, end_date)


@router.get("/dashboard/activity")
def dashboard_activity(
    period: str = Query("this_month"),
    employee: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    return {"series": MetricsService(db).activity_trend(period, employee, category)}


@router.get("/dashboard/pipeline")
def dashboard_pipeline(
    employee: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    service = MetricsService(db)
    return {
        "funnel": service.pipeline_funnel(employee, category),
        "stage_distribution": service.overview("all", employee, category)["stage_distribution"],
    }


@router.get("/dashboard/conversion")
def dashboard_conversion(
    employee: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    return MetricsService(db).conversion(employee, category)


@router.get("/employees", response_model=list[EmployeeResponse])
def list_employees(db: Session = Depends(get_db), _: User = Depends(require_sales_access)):
    return db.query(Employee).order_by(Employee.name).all()


@router.get("/employees/{employee_id}/performance")
def employee_performance(
    employee_id: int,
    period: str = Query("this_month"),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    perf = MetricsService(db).employee_performance(period)
    row = next((p for p in perf if p["employee"] == employee.name), None)
    targets = MetricsService(db).targets_vs_actual("today", employee.name)
    return {"employee": employee.name, "metrics": row, "targets": targets}


@router.get("/leads", response_model=list[LeadResponse])
def list_leads(
    search: str | None = Query(None),
    employee: str | None = Query(None),
    category: str | None = Query(None),
    stage: str | None = Query(None),
    limit: int = Query(500, le=2000),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    q = db.query(Lead, Employee.name).outerjoin(Employee, Lead.employee_id == Employee.id)
    if employee and employee.lower() != "all":
        q = q.filter(Employee.name == employee)
    if category and category.lower() != "all":
        q = q.filter(Lead.category == category)
    if stage and stage.lower() != "all":
        q = q.filter(Lead.current_stage == stage)
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(
            (Lead.company_name.ilike(like))
            | (Lead.contact_name.ilike(like))
            | (Lead.email.ilike(like))
            | (Lead.linkedin_url.ilike(like))
        )
    rows = q.order_by(Lead.updated_at.desc()).offset(offset).limit(limit).all()
    results = []
    for lead, employee_name in rows:
        item = LeadResponse.model_validate(lead)
        item.employee_name = employee_name or "—"
        results.append(item)
    return results


@router.get("/leads/count")
def count_leads(db: Session = Depends(get_db), _: User = Depends(require_sales_access)):
    return {"count": db.query(func.count(Lead.id)).scalar() or 0}


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
def get_lead(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_sales_access)):
    row = (
        db.query(Lead, Employee.name)
        .outerjoin(Employee, Lead.employee_id == Employee.id)
        .filter(Lead.id == lead_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead, employee_name = row
    activities = db.query(Activity).filter(Activity.lead_id == lead.id).order_by(Activity.activity_date.asc(), Activity.id.asc()).all()
    detail = LeadDetailResponse.model_validate(lead)
    detail.employee_name = employee_name
    detail.activities = [ActivityResponse.model_validate(a) for a in activities]
    return detail


@router.get("/activities")
def list_activities(
    period: str = Query("this_month"),
    employee: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    return {"series": MetricsService(db).activity_trend(period, employee, category)}


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), user: User = Depends(require_sales_access)):
    cats = [row[0] for row in db.query(Lead.category).distinct().order_by(Lead.category).all()]
    return {"categories": cats}


@router.get("/reports/summary")
def reports_summary(
    period: str = Query("this_month"),
    employee: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_sales_access),
):
    service = MetricsService(db)
    return {
        "overview": service.overview(period, employee, category),
        "employees": service.employee_performance(period, category),
        "categories": service.category_performance(period),
        "conversion": service.conversion(employee, category),
        "targets": service.targets_vs_actual(period if period in {"today", "this_week", "this_month"} else "today", employee),
    }


@router.get("/settings/sources", response_model=list[DataSourceResponse])
def list_sources(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(DataSource).order_by(DataSource.employee_name, DataSource.name).all()


@router.get("/settings/targets")
def list_targets(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return MetricsService(db).targets_vs_actual("today")


@router.post("/sync", response_model=SyncStatusResponse)
def trigger_sync(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cleanup_stale_sync_runs(db)
    if is_sync_running():
        return SyncStatusResponse(status="running", message="Sync already in progress")
    started = start_background_sync()
    if not started:
        return SyncStatusResponse(status="running", message="Sync already in progress")
    return SyncStatusResponse(status="started", message="Sync started in background — refresh status in a few seconds")


@router.get("/sync/status", response_model=SyncStatusResponse)
def sync_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if is_sync_running():
        return SyncStatusResponse(status="running", message="Sync in progress")
    run = db.query(SyncRun).order_by(SyncRun.id.desc()).first()
    if not run:
        return SyncStatusResponse(status="never")
    return SyncStatusResponse(
        status=run.status,
        last_sync_at=run.finished_at,
        message=run.message,
        rows_processed=run.rows_processed,
        leads_upserted=run.leads_upserted,
    )


import json
import re

from pydantic import BaseModel, Field

from app.core.text_guard import require_text
from app.services.column_map import fields_for, suggest_mapping
from app.services.sheets_client import GoogleSheetsClient

_SPREADSHEET = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_GID = re.compile(r"(?:[?&#]|^)gid=(\d+)")


class SheetPreviewIn(BaseModel):
    spreadsheet_url: str = Field(min_length=12, max_length=500)
    sheet_gid: int | None = None
    data_type: str = "lead_pipeline"


class SourceCreateIn(BaseModel):
    name: str
    employee_name: str
    category: str
    data_type: str = "lead_pipeline"
    spreadsheet_id: str
    sheet_gid: int
    column_map: dict[str, str]


def _checked_type(value: str) -> str:
    if value not in {"lead_pipeline", "linkedin"}:
        raise HTTPException(status_code=400, detail="Choose lead pipeline or LinkedIn")
    return value


@router.post("/settings/sources/preview")
def preview_source(payload: SheetPreviewIn, _: User = Depends(require_admin)):
    match = _SPREADSHEET.search(payload.spreadsheet_url.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Paste a Google Sheets link")
    spreadsheet_id = match.group(1)
    gid_match = _GID.search(payload.spreadsheet_url)
    gid = payload.sheet_gid if payload.sheet_gid is not None else (int(gid_match.group(1)) if gid_match else None)
    data_type = _checked_type(payload.data_type)
    try:
        client = GoogleSheetsClient()
        titles = client.get_sheet_titles(spreadsheet_id)
        if gid is None:
            gid = next(iter(titles), None)
        if gid is None:
            raise HTTPException(status_code=400, detail="This spreadsheet has no visible tabs")
        preview = client.preview_sheet(spreadsheet_id, gid)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read that sheet. Check the link and that the service account can view it.") from exc
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_gid": gid,
        "title": preview["title"],
        "headers": preview["headers"],
        "sample": preview["sample"],
        "tabs": preview["tabs"],
        "suggestions": suggest_mapping(preview["headers"], data_type),
    }


@router.post("/settings/sources", response_model=DataSourceResponse)
def create_source(payload: SourceCreateIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    data_type = _checked_type(payload.data_type)
    allowed = {field.key for field in fields_for(data_type)}
    column_map = {key: value.strip() for key, value in payload.column_map.items() if key in allowed and value.strip()}
    missing = [field.label for field in fields_for(data_type) if field.required and not column_map.get(field.key)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Map the required column: {missing[0]}")
    employee = db.query(Employee).filter(Employee.name == payload.employee_name.strip()).first()
    if not employee:
        raise HTTPException(status_code=400, detail="Choose an employee that already exists")
    source = DataSource(
        name=require_text(payload.name, max_length=120, allow_newlines=False),
        employee_name=employee.name,
        category=require_text(payload.category, max_length=80, allow_newlines=False),
        spreadsheet_id=payload.spreadsheet_id.strip(),
        sheet_gid=payload.sheet_gid,
        data_type=data_type,
        column_map=json.dumps(column_map),
        is_active=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source

