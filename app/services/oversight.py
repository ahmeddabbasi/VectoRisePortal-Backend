"""Team oversight metrics. Counts come from live tables. Dates are UTC."""

from datetime import datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import Date, String, and_, case, cast, func, or_
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.employee import Employee
from app.models.hr_evaluation import HREvaluation
from app.models.task import Task
from app.models.task_review import TaskReview
from app.models.team_lead import TeamLeadAssignment
from app.models.user import User
from app.services.activity_log import CLOSED_STATUSES, describe, utc_today, utcnow
from app.services.hierarchy import HierarchyService
from app.services.settings_service import SettingsService

OPEN_EXCLUDED = ("completed", "cancelled", "rejected")
SORTS = {
    "name": Employee.name,
    "team_size": None,
    "open_tasks": None,
    "overdue_tasks": None,
    "on_time_rate": None,
    "pending_reviews": None,
    "average_rating": None,
    "last_activity": None,
}


class OversightScope:
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.hierarchy = HierarchyService(db)
        self.admin = user.role == "admin"

    def reports(self, employee_id: int | None) -> list[int]:
        if not employee_id:
            return []
        return self.hierarchy.report_ids(employee_id)

    def is_plain_employee(self) -> bool:
        if self.admin:
            return False
        return not self.reports(self.user.employee_id)

    def require_team_access(self) -> None:
        if self.is_plain_employee():
            raise HTTPException(status_code=403, detail="You can only view your own oversight data")

    def visible_employee_ids(self) -> set[int] | None:
        if self.admin:
            return None
        if not self.user.employee_id:
            return set()
        visible = {self.user.employee_id}
        direct = self.reports(self.user.employee_id)
        visible.update(direct)
        for report_id in direct:
            visible.update(self.reports(report_id))
        return visible

    def require_employee(self, employee_id: int) -> None:
        visible = self.visible_employee_ids()
        if visible is not None and employee_id not in visible:
            raise HTTPException(status_code=403, detail="You cannot view that employee")

    def require_team(self, lead_id: int) -> None:
        if self.admin:
            if not self.reports(lead_id):
                raise HTTPException(status_code=404, detail="That person is not leading a team")
            return
        allowed = set(self.lead_ids())
        if lead_id not in allowed:
            raise HTTPException(status_code=403, detail="You cannot view that team")

    def lead_ids(self) -> list[int] | None:
        if self.admin:
            return None
        self.require_team_access()
        found = []
        if self.reports(self.user.employee_id):
            found.append(self.user.employee_id)
        for report_id in self.reports(self.user.employee_id):
            if self.reports(report_id) and report_id not in found:
                found.append(report_id)
        return found

    def require_activity_filters(self, actor_id: int | None, team_lead_id: int | None, employee_id: int | None) -> None:
        self.require_team_access()
        if employee_id:
            self.require_employee(employee_id)
        if team_lead_id:
            self.require_team(team_lead_id)
        if actor_id and not self.admin:
            actor = self.db.get(User, actor_id)
            if not actor or (actor.employee_id and actor.employee_id not in (self.visible_employee_ids() or set())):
                if actor and actor.id != self.user.id:
                    raise HTTPException(status_code=403, detail="You cannot view that activity")


def _settings(db: Session) -> dict[str, int]:
    service = SettingsService(db)
    return {
        "inactive_days": service.get_int("oversight_inactive_days", 7),
        "task_overdue_days": service.get_int("oversight_task_overdue_days", 1),
        "review_pending_days": service.get_int("oversight_review_pending_days", 3),
        "review_period_days": service.get_int("oversight_review_period_days", 30),
    }


def _overdue():
    return and_(Task.due_date.isnot(None), Task.due_date < utc_today(), Task.status.notin_(CLOSED_STATUSES))


def _open():
    return Task.status.notin_(OPEN_EXCLUDED)


def _stuck(inactive_days: int):
    cutoff = utcnow() - timedelta(days=inactive_days)
    return or_(Task.status == "blocked", and_(_open(), Task.updated_at < cutoff))


def _pending():
    reviewed = _reviewed_ids()
    return and_(Task.status == "completed", Task.id.notin_(reviewed))


def _reviewed_ids():
    return select_task_review_ids()


def select_task_review_ids():
    from sqlalchemy import select

    return select(TaskReview.task_id)


def _member_ids(lead_column):
    from sqlalchemy import select

    return select(TeamLeadAssignment.employee_id).where(TeamLeadAssignment.team_lead_id == lead_column)


def _in_range(column, date_from, date_to):
    filters = []
    if date_from:
        filters.append(column >= datetime.combine(date_from, time.min))
    if date_to:
        filters.append(column < datetime.combine(date_to + timedelta(days=1), time.min))
    return filters


def _on_time():
    completed_day = func.substr(cast(Task.completed_at, String), 1, 10)
    due_day = func.substr(cast(Task.due_date, String), 1, 10)
    return and_(Task.status == "completed", Task.due_date.isnot(None), Task.completed_at.isnot(None), completed_day <= due_day)


def _rate(numerator: int, denominator: int):
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _days(seconds):
    if seconds is None:
        return None
    return round(float(seconds) / 86400, 1)


class OversightService:
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.scope = OversightScope(db, user)
        self.thresholds = _settings(db)

    def summary(self) -> dict:
        self.scope.require_team_access()
        visible = self.scope.visible_employee_ids()
        employees = self.db.query(Employee).filter(Employee.status == "active")
        if visible is not None:
            employees = employees.filter(Employee.id.in_(visible))
        employee_ids = [row.id for row in employees.all()]
        led = {
            row[0]
            for row in self.db.query(TeamLeadAssignment.employee_id)
            .filter(TeamLeadAssignment.employee_id.in_(employee_ids) if employee_ids else False)
            .all()
        } if employee_ids else set()
        no_lead = [item for item in employee_ids if item not in led]
        lead_ids = self.scope.lead_ids()
        team_query = self.db.query(func.count(func.distinct(TeamLeadAssignment.team_lead_id)))
        if lead_ids is not None:
            team_query = team_query.filter(TeamLeadAssignment.team_lead_id.in_(lead_ids or [-1]))
        tasks = self.db.query(Task)
        if visible is not None:
            tasks = tasks.filter(Task.assigned_employee_id.in_(visible or [-1]))
        overdue = tasks.filter(_overdue()).count()
        pending = tasks.filter(_pending()).count()
        inactive = sum(1 for row in self._team_rows(page=1, page_size=1000)["items"] if row["inactive"])
        no_lead_rows = self.db.query(Employee).filter(Employee.id.in_(no_lead or [-1])).order_by(Employee.name).all()
        return {
            "employees": len(employee_ids),
            "teams": int(team_query.scalar() or 0),
            "employees_without_lead": len(no_lead),
            "unassigned": [{"id": row.id, "name": row.name, "job_title": row.job_title} for row in no_lead_rows],
            "overdue_tasks": overdue,
            "pending_reviews": pending,
            "inactive_teams": inactive,
            "thresholds": self.thresholds,
            "timezone": "UTC",
        }

    def teams(self, *, page: int, page_size: int, search: str | None, sort: str, direction: str, date_from, date_to, focus: str | None) -> dict:
        self.scope.require_team_access()
        return self._team_rows(page, page_size, search, sort, direction, date_from, date_to, focus)

    def _team_rows(self, page=1, page_size=25, search=None, sort="name", direction="asc", date_from=None, date_to=None, focus=None) -> dict:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        inactive_days = self.thresholds["inactive_days"]
        review_days = self.thresholds["review_pending_days"]
        period_days = self.thresholds["review_period_days"]
        period_start = utcnow() - timedelta(days=period_days)
        review_cutoff = utcnow() - timedelta(days=review_days)
        inactive_cutoff = utcnow() - timedelta(days=inactive_days)
        members = _member_ids(Employee.id)
        lead_user = self.db.query(User.id).filter(User.employee_id == Employee.id).correlate(Employee).scalar_subquery()

        def member_task_count(*filters):
            query = (
                self.db.query(func.count(func.distinct(Task.id)))
                .filter(Task.assigned_employee_id.in_(members), *filters)
                .correlate(Employee)
            )
            return query.scalar_subquery()

        def assigned_count(*filters):
            return (
                self.db.query(func.count(func.distinct(Task.id)))
                .filter(Task.assigned_by_id == lead_user, Task.assigned_employee_id.in_(members), *filters)
                .correlate(Employee)
                .scalar_subquery()
            )

        completed_filters = [Task.status == "completed", *_in_range(Task.completed_at, date_from, date_to)]
        assigned_filters = _in_range(Task.created_at, date_from, date_to)
        on_time_filters = [_on_time(), *_in_range(Task.completed_at, date_from, date_to)]
        due_filters = [Task.status == "completed", Task.due_date.isnot(None), *_in_range(Task.completed_at, date_from, date_to)]
        open_count = member_task_count(_open())
        overdue_count = member_task_count(_overdue())
        completed_count = member_task_count(*completed_filters)
        on_time_count = member_task_count(*on_time_filters)
        due_count = member_task_count(*due_filters)
        tasks_assigned = assigned_count(*assigned_filters)
        pending_count = member_task_count(_pending())
        overdue_review_count = member_task_count(_pending(), Task.completed_at.isnot(None), Task.completed_at < review_cutoff)
        stuck_count = member_task_count(_stuck(inactive_days))
        team_size = (
            self.db.query(func.count(func.distinct(TeamLeadAssignment.employee_id)))
            .filter(TeamLeadAssignment.team_lead_id == Employee.id)
            .correlate(Employee)
            .scalar_subquery()
        )
        covered = (
            self.db.query(func.count(func.distinct(HREvaluation.employee_id)))
            .filter(
                HREvaluation.evaluator_id == lead_user,
                HREvaluation.employee_id.in_(members),
                HREvaluation.created_at >= period_start,
            )
            .correlate(Employee)
            .scalar_subquery()
        )
        given = (
            self.db.query(func.count(HREvaluation.id))
            .filter(HREvaluation.evaluator_id == lead_user, HREvaluation.employee_id.in_(members), HREvaluation.created_at >= period_start)
            .correlate(Employee)
            .scalar_subquery()
        )
        rating = (
            self.db.query(func.avg(TaskReview.rating))
            .join(Task, Task.id == TaskReview.task_id)
            .filter(TaskReview.reviewer_user_id == lead_user, TaskReview.rating.isnot(None), Task.assigned_employee_id.in_(members))
            .correlate(Employee)
            .scalar_subquery()
        )
        log_max = (
            self.db.query(func.max(ActivityLog.created_at))
            .filter(or_(ActivityLog.team_lead_id == Employee.id, ActivityLog.target_employee_id.in_(members), ActivityLog.actor_id == lead_user))
            .correlate(Employee)
            .scalar_subquery()
        )
        active_at = (
            self.db.query(func.max(User.last_active_at))
            .filter(User.employee_id == Employee.id)
            .correlate(Employee)
            .scalar_subquery()
        )
        query = self.db.query(
            Employee.id,
            Employee.name,
            Employee.job_title,
            team_size.label("team_size"),
            open_count.label("open_tasks"),
            overdue_count.label("overdue_tasks"),
            completed_count.label("completed_tasks"),
            tasks_assigned.label("tasks_assigned"),
            on_time_count.label("on_time_count"),
            due_count.label("due_count"),
            pending_count.label("pending_reviews"),
            overdue_review_count.label("overdue_reviews"),
            stuck_count.label("stuck_tasks"),
            covered.label("reviews_covered"),
            given.label("reviews_given"),
            rating.label("average_rating"),
            log_max.label("log_activity"),
            active_at.label("session_activity"),
        ).filter(Employee.id.in_(self.db.query(TeamLeadAssignment.team_lead_id)))
        allowed = self.scope.lead_ids()
        if allowed is not None:
            query = query.filter(Employee.id.in_(allowed or [-1]))
        if search:
            term = search.replace("%", "").replace("_", "").strip().lower()
            if term:
                query = query.filter(func.lower(Employee.name).like(f"%{term}%"))
        if focus == "inactive":
            query = query.filter(or_(log_max.is_(None), log_max < inactive_cutoff), or_(active_at.is_(None), active_at < inactive_cutoff))
        if focus == "overdue_reviews" or focus == "pending":
            query = query.filter(pending_count > 0)
        if focus == "overdue":
            query = query.filter(overdue_count > 0)
        sort_key = sort if sort in SORTS else "name"
        sort_column = {
            "name": Employee.name,
            "team_size": team_size,
            "open_tasks": open_count,
            "overdue_tasks": overdue_count,
            "on_time_rate": on_time_count,
            "pending_reviews": pending_count,
            "average_rating": rating,
            "last_activity": log_max,
        }[sort_key]
        query = query.order_by(sort_column.desc() if direction == "desc" else sort_column.asc(), Employee.id.asc())
        total = query.order_by(None).count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        items = []
        for row in rows:
            last_values = [value for value in (row.log_activity, row.session_activity) if value]
            last_activity = max(last_values) if last_values else None
            items.append({
                "id": row.id,
                "name": row.name,
                "job_title": row.job_title,
                "team_size": int(row.team_size or 0),
                "open_tasks": int(row.open_tasks or 0),
                "overdue_tasks": int(row.overdue_tasks or 0),
                "completed_tasks": int(row.completed_tasks or 0),
                "tasks_assigned": int(row.tasks_assigned or 0),
                "on_time_rate": _rate(int(row.on_time_count or 0), int(row.due_count or 0)),
                "pending_reviews": int(row.pending_reviews or 0),
                "overdue_reviews": int(row.overdue_reviews or 0),
                "stuck_tasks": int(row.stuck_tasks or 0),
                "reviews_given": int(row.reviews_given or 0),
                "reviews_due": max(int(row.team_size or 0) - int(row.reviews_covered or 0), 0),
                "average_rating": round(float(row.average_rating), 2) if row.average_rating is not None else None,
                "last_activity": last_activity.isoformat() + "Z" if last_activity else None,
                "inactive": last_activity is None or last_activity < inactive_cutoff,
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size, "timezone": "UTC"}

    def team_detail(self, lead_id: int) -> dict:
        self.scope.require_team(lead_id)
        lead = self.db.get(Employee, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Employee not found")
        manager_ids = HierarchyService(self.db).lead_ids(lead_id)
        managers = HierarchyService(self.db).people(manager_ids)
        metrics = next((item for item in self._team_rows(page=1, page_size=1000)["items"] if item["id"] == lead_id), None)
        user = self.db.query(User).filter(User.employee_id == lead_id).first()
        hierarchy = HierarchyService(self.db)
        members = hierarchy.people(hierarchy.report_ids(lead_id))
        member_ids = [person["id"] for person in members]
        counts = {}
        if member_ids:
            rows = (
                self.db.query(
                    Task.assigned_employee_id,
                    func.sum(case((_open(), 1), else_=0)),
                    func.sum(case((_overdue(), 1), else_=0)),
                )
                .filter(Task.assigned_employee_id.in_(member_ids))
                .group_by(Task.assigned_employee_id)
                .all()
            )
            counts = {
                employee_id: {"open_tasks": int(open_count or 0), "overdue_tasks": int(overdue_count or 0)}
                for employee_id, open_count, overdue_count in rows
            }
        for person in members:
            person.update(counts.get(person["id"], {"open_tasks": 0, "overdue_tasks": 0}))
        return {
            "employee": {"id": lead.id, "name": lead.name, "job_title": lead.job_title, "email": lead.email},
            "managers": managers,
            "members": members,
            "metrics": metrics,
            "last_active_at": user.last_active_at.isoformat() + "Z" if user and user.last_active_at else None,
            "timezone": "UTC",
        }

    def employee_detail(self, employee_id: int) -> dict:
        self.scope.require_employee(employee_id)
        employee = self.db.get(Employee, employee_id)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        hierarchy = HierarchyService(self.db)
        leads = hierarchy.people(hierarchy.lead_ids(employee_id))
        managers = []
        seen = set()
        for lead_id in hierarchy.lead_ids(employee_id):
            for manager in hierarchy.people(hierarchy.lead_ids(lead_id)):
                if manager["id"] not in seen:
                    seen.add(manager["id"])
                    managers.append(manager)
        tasks = self.db.query(Task).filter(Task.assigned_employee_id == employee_id).all()
        completed = [task for task in tasks if task.status == "completed"]
        with_due = [task for task in completed if task.due_date and task.completed_at]
        on_time = [task for task in with_due if task.completed_at.date() <= task.due_date]
        reviewed = {row[0] for row in self.db.query(TaskReview.task_id).join(Task).filter(Task.assigned_employee_id == employee_id).all()}
        ratings = [
            row[0]
            for row in self.db.query(TaskReview.rating)
            .join(Task, Task.id == TaskReview.task_id)
            .filter(Task.assigned_employee_id == employee_id, TaskReview.rating.isnot(None))
            .all()
        ]
        from app.models.task_document import TaskDocument

        documents = (
            self.db.query(TaskDocument.id, TaskDocument.original_name, TaskDocument.created_at, TaskDocument.task_id, Task.title)
            .join(Task, Task.id == TaskDocument.task_id)
            .filter(Task.assigned_employee_id == employee_id)
            .order_by(TaskDocument.created_at.desc())
            .all()
        )
        from app.models.system_setting import SystemSetting

        launch = self.db.query(SystemSetting).filter(SystemSetting.key == "oversight_launch_at").first()
        assignment_rows = (
            self.db.query(ActivityLog)
            .filter(
                ActivityLog.target_employee_id == employee_id,
                ActivityLog.action_type.in_(("team_lead_assigned", "team_lead_removed")),
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(50)
            .all()
        )
        return {
            "employee": {"id": employee.id, "name": employee.name, "job_title": employee.job_title, "email": employee.email},
            "team_leads": leads,
            "managers": managers,
            "metrics": {
                "open_tasks": sum(1 for task in tasks if task.status not in OPEN_EXCLUDED),
                "completed_tasks": len(completed),
                "overdue_tasks": sum(1 for task in tasks if task.due_date and task.due_date < utc_today() and task.status not in CLOSED_STATUSES),
                "on_time_rate": _rate(len(on_time), len(with_due)),
                "reviews_received": len(reviewed),
                "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "documents_uploaded": len(documents),
                "stuck_tasks": sum(1 for task in tasks if task.status == "blocked" or (task.status not in OPEN_EXCLUDED and task.updated_at and task.updated_at < utcnow() - timedelta(days=self.thresholds["inactive_days"]))),
            },
            "tasks": [
                {"id": task.id, "title": task.title, "status": task.status, "due_date": task.due_date.isoformat() if task.due_date else None, "completed_at": task.completed_at.isoformat() + "Z" if task.completed_at else None}
                for task in tasks
            ],
            "documents": [
                {"id": row.id, "name": row.original_name, "task_id": row.task_id, "task_title": row.title, "created_at": row.created_at.isoformat() + "Z"}
                for row in documents
            ],
            "reviews": self._reviews_for_employee(employee_id),
            "launch_at": launch.value if launch else None,
            "assignments": [_activity_item(row) for row in assignment_rows],
            "timezone": "UTC",
        }

    def _reviews_for_employee(self, employee_id: int) -> dict:
        task_reviews = (
            self.db.query(TaskReview, Task)
            .join(Task, Task.id == TaskReview.task_id)
            .filter(Task.assigned_employee_id == employee_id)
            .order_by(TaskReview.created_at.desc())
            .all()
        )
        evaluations = self.db.query(HREvaluation).filter(HREvaluation.employee_id == employee_id).order_by(HREvaluation.created_at.desc()).all()
        return {
            "tasks": [
                {"id": review.id, "task_id": task.id, "title": task.title, "status": review.status, "rating": review.rating, "comment": review.comments, "created_at": review.created_at.isoformat() + "Z"}
                for review, task in task_reviews
            ],
            "performance": [
                {"id": item.id, "score": item.score, "comment": item.comments, "period_start": item.period_start.isoformat(), "period_end": item.period_end.isoformat(), "created_at": item.created_at.isoformat() + "Z"}
                for item in evaluations
            ],
        }

    def activity(self, *, page: int, page_size: int, actor_id=None, team_lead_id=None, employee_id=None, action_type=None, date_from=None, date_to=None, lead_only: int | None = None) -> dict:
        if lead_only:
            self.scope.require_team(lead_only)
        elif self.scope.is_plain_employee():
            raise HTTPException(status_code=403, detail="You can only view your own oversight data")
        else:
            self.scope.require_activity_filters(actor_id, team_lead_id, employee_id)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        query = self._activity_query(actor_id, team_lead_id, employee_id, action_type, date_from, date_to, lead_only)
        total = query.order_by(None).count()
        rows = query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"items": [_activity_item(row) for row in rows], "total": total, "page": page, "page_size": page_size, "timezone": "UTC"}

    def _activity_query(self, actor_id, team_lead_id, employee_id, action_type, date_from, date_to, lead_only):
        query = self.db.query(ActivityLog)
        visible = self.scope.visible_employee_ids()
        if lead_only:
            members = HierarchyService(self.db).report_ids(lead_only)
            query = query.filter(or_(ActivityLog.team_lead_id == lead_only, ActivityLog.target_employee_id.in_(members or [-1])))
        elif visible is not None:
            actor_ids = [row[0] for row in self.db.query(User.id).filter(User.employee_id.in_(visible or [-1])).all()]
            query = query.filter(or_(
                ActivityLog.target_employee_id.in_(visible or [-1]),
                ActivityLog.team_lead_id.in_(visible or [-1]),
                ActivityLog.actor_id.in_(actor_ids or [-1]),
            ))
        if actor_id:
            query = query.filter(ActivityLog.actor_id == actor_id)
        if team_lead_id:
            query = query.filter(ActivityLog.team_lead_id == team_lead_id)
        if employee_id:
            query = query.filter(ActivityLog.target_employee_id == employee_id)
        if action_type:
            query = query.filter(ActivityLog.action_type == action_type)
        for clause in _in_range(ActivityLog.created_at, date_from, date_to):
            query = query.filter(clause)
        return query

    def hierarchy(self) -> dict:
        self.scope.require_team_access()
        allowed = self.scope.lead_ids()
        pairs = self.db.query(TeamLeadAssignment).all()
        if allowed is not None:
            allowed_set = set(allowed)
            pairs = [pair for pair in pairs if pair.team_lead_id in allowed_set or pair.employee_id in allowed_set]
        overdue_rows = self.db.query(Task.assigned_employee_id, func.count(Task.id)).filter(_overdue()).group_by(Task.assigned_employee_id).all()
        overdue = {employee_id: count for employee_id, count in overdue_rows}
        by_member: dict[int, list[int]] = {}
        lead_counts: dict[int, int] = {}
        for pair in pairs:
            by_member.setdefault(pair.employee_id, []).append(pair.team_lead_id)
            lead_counts[pair.team_lead_id] = lead_counts.get(pair.team_lead_id, 0) + 1
        people_ids = set(lead_counts) | set(by_member)
        people = {row.id: row for row in self.db.query(Employee).filter(Employee.id.in_(people_ids or [-1])).all()}
        children: dict[int, list[int]] = {}
        for pair in pairs:
            children.setdefault(pair.team_lead_id, []).append(pair.employee_id)

        def node(employee_id: int) -> dict:
            person = people.get(employee_id)
            member_ids = children.get(employee_id, [])
            own = int(overdue.get(employee_id, 0))
            child_nodes = [node(child_id) for child_id in member_ids]
            return {
                "id": employee_id,
                "name": person.name if person else "Employee",
                "job_title": person.job_title if person else None,
                "overdue_tasks": own + sum(child["overdue_tasks"] for child in child_nodes),
                "also_reports_to_others": len(by_member.get(employee_id, [])) > 1,
                "is_lead": employee_id in lead_counts,
                "children": child_nodes,
            }

        roots = [lead_id for lead_id in lead_counts if lead_id not in by_member]
        if allowed is not None and self.scope.user.employee_id in allowed:
            roots = [self.scope.user.employee_id]
        return {"roots": [node(root_id) for root_id in roots], "timezone": "UTC"}

    def trends(self, date_from, date_to) -> dict:
        self.scope.require_team_access()
        visible = self.scope.visible_employee_ids()
        dialect = self.db.bind.dialect.name if self.db.bind else "sqlite"
        bucket_created = func.strftime("%Y-%W", Task.created_at) if dialect != "postgresql" else func.to_char(func.date_trunc("week", Task.created_at), "IYYY-IW")
        bucket_completed = func.strftime("%Y-%W", Task.completed_at) if dialect != "postgresql" else func.to_char(func.date_trunc("week", Task.completed_at), "IYYY-IW")
        bucket_due = func.strftime("%Y-%W", Task.due_date) if dialect != "postgresql" else func.to_char(func.date_trunc("week", Task.due_date), "IYYY-IW")
        created = self.db.query(bucket_created.label("bucket"), func.count(Task.id)).filter(*_in_range(Task.created_at, date_from, date_to))
        completed = self.db.query(bucket_completed.label("bucket"), func.count(Task.id)).filter(Task.status == "completed", *_in_range(Task.completed_at, date_from, date_to))
        on_time = self.db.query(bucket_completed.label("bucket"), func.count(Task.id)).filter(_on_time(), *_in_range(Task.completed_at, date_from, date_to))
        with_due = self.db.query(bucket_completed.label("bucket"), func.count(Task.id)).filter(Task.status == "completed", Task.due_date.isnot(None), *_in_range(Task.completed_at, date_from, date_to))
        overdue = self.db.query(bucket_due.label("bucket"), func.count(Task.id)).filter(_overdue(), *_in_range(Task.due_date, date_from, date_to))
        if visible is not None:
            created = created.filter(Task.assigned_employee_id.in_(visible or [-1]))
            completed = completed.filter(Task.assigned_employee_id.in_(visible or [-1]))
            on_time = on_time.filter(Task.assigned_employee_id.in_(visible or [-1]))
            with_due = with_due.filter(Task.assigned_employee_id.in_(visible or [-1]))
            overdue = overdue.filter(Task.assigned_employee_id.in_(visible or [-1]))
        created_map = dict(created.group_by(bucket_created).all())
        completed_map = dict(completed.group_by(bucket_completed).all())
        on_time_map = dict(on_time.group_by(bucket_completed).all())
        due_map = dict(with_due.group_by(bucket_completed).all())
        overdue_map = dict(overdue.group_by(bucket_due).all())
        weeks = sorted(set(created_map) | set(completed_map) | set(due_map) | set(overdue_map))
        return {
            "weeks": [
                {
                    "week": week,
                    "created": int(created_map.get(week, 0)),
                    "completed": int(completed_map.get(week, 0)),
                    "on_time_rate": _rate(int(on_time_map.get(week, 0)), int(due_map.get(week, 0))),
                    "overdue": int(overdue_map.get(week, 0)),
                }
                for week in weeks
                if week
            ],
            "timezone": "UTC",
        }

    def turnaround_days(self, lead_id: int):
        self.scope.require_team(lead_id)
        members = HierarchyService(self.db).report_ids(lead_id) or [-1]
        first_review = (
            self.db.query(TaskReview.task_id.label("task_id"), func.min(TaskReview.created_at).label("reviewed_at"))
            .group_by(TaskReview.task_id)
            .subquery()
        )
        dialect = self.db.bind.dialect.name if self.db.bind else "sqlite"
        if dialect == "postgresql":
            seconds = func.extract("epoch", first_review.c.reviewed_at - Task.completed_at)
        else:
            seconds = (func.julianday(first_review.c.reviewed_at) - func.julianday(Task.completed_at)) * 86400
        value = (
            self.db.query(func.avg(seconds))
            .join(first_review, first_review.c.task_id == Task.id)
            .filter(
                Task.assigned_employee_id.in_(members),
                Task.completed_at.isnot(None),
                first_review.c.reviewed_at >= Task.completed_at,
            )
            .scalar()
        )
        return _days(value)


def _activity_item(row: ActivityLog) -> dict:
    meta = row.metadata_json or {}
    return {
        "id": row.id,
        "action_type": row.action_type,
        "sentence": describe(row),
        "historical": bool(meta.get("backfilled")),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "actor_id": row.actor_id,
        "actor_name": meta.get("actor_name"),
        "target_employee_id": row.target_employee_id,
        "target_name": meta.get("target_name"),
        "team_lead_id": row.team_lead_id,
        "task_id": meta.get("task_id") or (row.entity_id if row.entity_type == "task" else None),
    }
