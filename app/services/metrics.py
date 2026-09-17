from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.employee import Employee
from app.models.lead import Lead
from app.models.sync_run import SyncRun
from app.models.target import Target


def parse_period(period: str, custom_start: date | None = None, custom_end: date | None = None) -> tuple[date | None, date | None]:
    today = date.today()
    period = (period or "all").lower()
    if period == "today":
        return today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if period == "last_7_days":
        return today - timedelta(days=6), today
    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if period == "last_week":
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start, end
    if period == "this_month":
        return today.replace(day=1), today
    if period == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        return last_month_end.replace(day=1), last_month_end
    if period == "last_30_days":
        return today - timedelta(days=29), today
    if period == "custom" and custom_start and custom_end:
        return custom_start, custom_end
    return None, None


class MetricsService:
    def __init__(self, db: Session):
        self.db = db

    def _lead_query(
        self,
        employee: str | None = None,
        category: str | None = None,
        stage: str | None = None,
    ):
        q = self.db.query(Lead)
        if employee and employee.lower() != "all":
            q = q.join(Employee).filter(Employee.name == employee)
        if category and category.lower() != "all":
            q = q.filter(Lead.category == category)
        if stage and stage.lower() != "all":
            q = q.filter(Lead.current_stage == stage)
        return q

    def _activity_query(
        self,
        start: date | None,
        end: date | None,
        employee: str | None = None,
        category: str | None = None,
    ):
        q = self.db.query(Activity).join(Lead)
        if employee and employee.lower() != "all":
            q = q.join(Employee, Activity.employee_id == Employee.id).filter(Employee.name == employee)
        if category and category.lower() != "all":
            q = q.filter(Lead.category == category)
        if start and end:
            q = q.filter(Activity.activity_date >= start, Activity.activity_date <= end)
        return q

    def overview(
        self,
        period: str = "all",
        employee: str | None = None,
        category: str | None = None,
        custom_start: date | None = None,
        custom_end: date | None = None,
    ) -> dict[str, Any]:
        start, end = parse_period(period, custom_start, custom_end)
        leads = self._lead_query(employee, category)
        total_leads = leads.count()
        contacted = leads.filter(Lead.current_stage != "Not Contacted").count()
        stage_rows = (
            leads.with_entities(Lead.current_stage, func.count(Lead.id))
            .group_by(Lead.current_stage)
            .all()
        )
        stage_distribution = {stage or "Unknown": count for stage, count in stage_rows}

        activities = self._activity_query(start, end, employee, category)
        initial_emails = activities.filter(Activity.activity_type == "INITIAL_EMAIL").count()
        follow_ups = activities.filter(Activity.activity_type == "FOLLOW_UP").count()
        linkedin = activities.filter(
            Activity.activity_type.in_(["LINKEDIN_OUTREACH", "LINKEDIN_FOLLOW_UP"])
        ).count()
        replies = activities.filter(Activity.activity_type == "REPLY_RECEIVED").count()
        meetings = activities.filter(Activity.activity_type == "MEETING_BOOKED").count()

        opportunities = leads.filter(Lead.opportunity_status.isnot(None), Lead.opportunity_status != "").count()
        closed = leads.filter(Lead.opportunity_status.ilike("%closed won%")).count()
        awaiting_reply = leads.filter(Lead.current_stage == "Awaiting Reply").count()
        duplicates = leads.filter(Lead.is_duplicate.is_(True)).count()

        last_sync = self.db.query(SyncRun).order_by(SyncRun.finished_at.desc()).first()

        return {
            "total_leads": total_leads,
            "leads_contacted": contacted,
            "initial_emails": initial_emails,
            "emails_sent": initial_emails,
            "follow_ups": follow_ups,
            "linkedin_outreach": linkedin,
            "replies": replies,
            "meetings": meetings,
            "opportunities": opportunities,
            "closed": closed,
            "awaiting_reply": awaiting_reply,
            "potential_duplicates": duplicates,
            "stage_distribution": stage_distribution,
            "period": period,
            "date_range": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
            "sync": {
                "status": last_sync.status if last_sync else "never",
                "last_sync_at": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
                "message": last_sync.message if last_sync else None,
            },
        }

    def activity_trend(
        self,
        period: str = "this_month",
        employee: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        start, end = parse_period(period)
        if not start or not end:
            start, end = date.today().replace(day=1), date.today()
        q = self._activity_query(start, end, employee, category)
        rows = (
            q.with_entities(Activity.activity_date, Activity.activity_type, func.count(Activity.id))
            .group_by(Activity.activity_date, Activity.activity_type)
            .all()
        )
        bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for act_date, act_type, count in rows:
            if not act_date:
                continue
            key = act_date.isoformat()
            bucket[key]["total"] += count
            if act_type == "INITIAL_EMAIL":
                bucket[key]["emails"] += count
            elif act_type == "FOLLOW_UP":
                bucket[key]["follow_ups"] += count
            elif act_type in {"LINKEDIN_OUTREACH", "LINKEDIN_FOLLOW_UP"}:
                bucket[key]["linkedin"] += count
            elif act_type == "REPLY_RECEIVED":
                bucket[key]["replies"] += count
            elif act_type == "MEETING_BOOKED":
                bucket[key]["meetings"] += count

        result: list[dict[str, Any]] = []
        current = start
        while current <= end:
            key = current.isoformat()
            vals = bucket.get(key, {})
            result.append(
                {
                    "date": key,
                    "total": vals.get("total", 0),
                    "emails": vals.get("emails", 0),
                    "follow_ups": vals.get("follow_ups", 0),
                    "linkedin": vals.get("linkedin", 0),
                    "replies": vals.get("replies", 0),
                    "meetings": vals.get("meetings", 0),
                }
            )
            current += timedelta(days=1)
        return result

    def employee_performance(
        self,
        period: str = "this_month",
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        start, end = parse_period(period)
        employees = self.db.query(Employee).filter(Employee.status == "active").all()
        results = []
        for emp in employees:
            lead_count = self._lead_query(emp.name, category).count()
            acts = self._activity_query(start, end, emp.name, category)
            results.append(
                {
                    "employee": emp.name,
                    "leads": lead_count,
                    "initial_emails": acts.filter(Activity.activity_type == "INITIAL_EMAIL").count(),
                    "follow_ups": acts.filter(Activity.activity_type == "FOLLOW_UP").count(),
                    "linkedin": acts.filter(
                        Activity.activity_type.in_(["LINKEDIN_OUTREACH", "LINKEDIN_FOLLOW_UP"])
                    ).count(),
                    "replies": acts.filter(Activity.activity_type == "REPLY_RECEIVED").count(),
                    "meetings": acts.filter(Activity.activity_type == "MEETING_BOOKED").count(),
                    "opportunities": self._lead_query(emp.name, category)
                    .filter(Lead.opportunity_status.isnot(None), Lead.opportunity_status != "")
                    .count(),
                }
            )
        return results

    def category_performance(self, period: str = "this_month") -> list[dict[str, Any]]:
        start, end = parse_period(period)
        categories = [row[0] for row in self.db.query(Lead.category).distinct().all()]
        results = []
        for cat in categories:
            leads = self._lead_query(category=cat).count()
            acts = self._activity_query(start, end, category=cat)
            replies = acts.filter(Activity.activity_type == "REPLY_RECEIVED").count()
            meetings = acts.filter(Activity.activity_type == "MEETING_BOOKED").count()
            results.append(
                {
                    "category": cat,
                    "leads": leads,
                    "replies": replies,
                    "meetings": meetings,
                    "contact_rate": round(replies / leads * 100, 1) if leads else 0,
                }
            )
        return sorted(results, key=lambda x: x["leads"], reverse=True)

    def conversion(self, employee: str | None = None, category: str | None = None) -> dict[str, Any]:
        leads = self._lead_query(employee, category)
        total = leads.count()
        contacted = leads.filter(Lead.current_stage != "Not Contacted").count()
        replies = leads.filter(Lead.reply_status.isnot(None)).count() + leads.filter(
            Lead.current_stage == "Replied"
        ).count()
        replies = min(replies, total)
        meetings = leads.filter(Lead.meeting_status.isnot(None), Lead.meeting_status != "").count()
        opportunities = leads.filter(Lead.opportunity_status.isnot(None), Lead.opportunity_status != "").count()
        closed = leads.filter(Lead.opportunity_status.ilike("%closed won%")).count()

        def pct(num: int, den: int) -> float:
            return round(num / den * 100, 1) if den else 0.0

        return {
            "contact_to_reply": pct(replies, contacted),
            "reply_to_meeting": pct(meetings, replies),
            "meeting_to_opportunity": pct(opportunities, meetings),
            "opportunity_to_closed": pct(closed, opportunities),
            "lead_to_meeting": pct(meetings, total),
            "counts": {
                "total_leads": total,
                "contacted": contacted,
                "replies": replies,
                "meetings": meetings,
                "opportunities": opportunities,
                "closed": closed,
            },
        }

    def pipeline_funnel(self, employee: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
        order = [
            "Not Contacted",
            "Initial Email",
            "Follow-up",
            "LinkedIn Follow-up",
            "Awaiting Reply",
            "Replied",
        ]
        stage_counts = dict(
            self._lead_query(employee, category)
            .with_entities(Lead.current_stage, func.count(Lead.id))
            .group_by(Lead.current_stage)
            .all()
        )
        total = sum(stage_counts.values())
        funnel = [{"stage": "Total Leads", "count": total}]
        for stage in order:
            funnel.append({"stage": stage, "count": stage_counts.get(stage, 0)})
        return funnel

    def targets_vs_actual(self, period: str = "today", employee: str | None = None) -> list[dict[str, Any]]:
        start, end = parse_period(period)
        employees = self.db.query(Employee)
        if employee and employee.lower() != "all":
            employees = employees.filter(Employee.name == employee)
        employees = employees.all()
        rows = []
        for emp in employees:
            targets = self.db.query(Target).filter(Target.employee_id == emp.id).all()
            acts = self._activity_query(start, end, emp.name)
            mapping = {
                "INITIAL_EMAIL": acts.filter(Activity.activity_type == "INITIAL_EMAIL").count(),
                "FOLLOW_UP": acts.filter(Activity.activity_type == "FOLLOW_UP").count(),
                "LINKEDIN_OUTREACH": acts.filter(Activity.activity_type == "LINKEDIN_OUTREACH").count(),
            }
            for target in targets:
                actual = mapping.get(target.activity_type, 0)
                pct = round(actual / target.target_value * 100, 1) if target.target_value else 0
                rows.append(
                    {
                        "employee": emp.name,
                        "activity_type": target.activity_type,
                        "target": target.target_value,
                        "actual": actual,
                        "percentage": pct,
                    }
                )
        return rows
