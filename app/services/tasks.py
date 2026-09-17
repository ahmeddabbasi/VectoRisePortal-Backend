from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session, selectinload

from app.models.employee import Employee
from app.models.enums import ExceptionType, TaskStatus
from app.models.task import Task
from app.models.task_checklist_item import TaskChecklistItem
from app.models.task_time_log import TaskTimeLog
from app.models.user import User
from app.services.audit import AuditService
from app.services.exceptions import ExceptionService
from app.services.notifications import NotificationService

CHECKLIST_TEMPLATES: dict[str, list[str]] = {
    "outreach": [
        "Review lead list",
        "Send initial emails",
        "Complete LinkedIn outreach",
        "Record responses",
        "Complete follow-ups",
        "Update CRM",
        "Submit daily report",
    ],
    "research": [
        "Define research scope",
        "Gather source materials",
        "Analyze findings",
        "Document conclusions",
        "Share summary with team",
    ],
    "general": [
        "Review task requirements",
        "Execute primary work",
        "Validate output",
        "Submit completion notes",
    ],
}


class TaskService:
    def __init__(self, db: Session):
        self.db = db
        self.exceptions = ExceptionService(db)
        self.audit = AuditService(db)

    def _generate_checklist(self, task: Task):
        template_key = (task.task_type or "general").lower()
        items = CHECKLIST_TEMPLATES.get(template_key, CHECKLIST_TEMPLATES["general"])
        for idx, label in enumerate(items):
            self.db.add(
                TaskChecklistItem(
                    task_id=task.id,
                    label=label,
                    sort_order=idx,
                    is_auto_generated=True,
                )
            )

    def create_task(self, data: dict, assigned_by: User | None = None) -> Task:
        task = Task(
            title=data["title"],
            description=data.get("description"),
            priority=data.get("priority", "medium"),
            assigned_employee_id=data["assigned_employee_id"],
            assigned_by_id=assigned_by.id if assigned_by else None,
            due_date=data.get("due_date"),
            estimated_minutes=data.get("estimated_minutes"),
            task_type=data.get("task_type", "general"),
            notes=data.get("notes"),
        )
        self.db.add(task)
        self.db.flush()
        if data.get("auto_checklist", True):
            self._generate_checklist(task)
        if assigned_by:
            self.audit.log("task_created", assigned_by, "task", task.id, None, {"title": task.title})
            NotificationService(self.db).notify_employee(
                task.assigned_employee_id,
                "New task assigned",
                f"You have been assigned: {task.title}",
                "task",
                "/employee/tasks",
            )
        return task

    def create_employee_task(self, employee_id: int, user: User, data: dict) -> Task:
        employee = self.db.get(Employee, employee_id)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        task = Task(
            title=data["title"],
            description=data.get("description"),
            priority=data.get("priority", "medium"),
            assigned_employee_id=employee_id,
            assigned_by_id=None,
            due_date=data.get("due_date") or date.today(),
            task_type=data.get("task_type", "general"),
            notes=data.get("notes"),
            status=TaskStatus.PENDING_APPROVAL,
        )
        self.db.add(task)
        self.db.flush()
        self.audit.log("task_submitted", user, "task", task.id, None, {"title": task.title})
        NotificationService(self.db).notify_admins(
            "Task approval needed",
            f"{employee.name} submitted a daily task: {task.title}",
            "task",
            "/admin/tasks",
        )
        return task

    def approve_task(self, task_id: int, admin: User) -> Task:
        task = self.db.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != TaskStatus.PENDING_APPROVAL:
            raise HTTPException(status_code=400, detail="Task is not pending approval")
        task.status = TaskStatus.NOT_STARTED
        self.audit.log("task_approved", admin, "task", task.id, None, {"title": task.title})
        NotificationService(self.db).notify_employee(
            task.assigned_employee_id,
            "Task approved",
            f"Your task was approved: {task.title}",
            "task",
            "/employee/tasks",
        )
        return task

    def reject_task(self, task_id: int, admin: User, reason: str | None = None) -> Task:
        task = self.db.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != TaskStatus.PENDING_APPROVAL:
            raise HTTPException(status_code=400, detail="Task is not pending approval")
        task.status = TaskStatus.REJECTED
        if reason:
            task.notes = reason
        self.audit.log("task_rejected", admin, "task", task.id, None, {"title": task.title})
        NotificationService(self.db).notify_employee(
            task.assigned_employee_id,
            "Task rejected",
            reason or f"Your task was not approved: {task.title}",
            "task",
            "/employee/tasks",
        )
        return task

    def _ensure_task_actionable(self, task: Task):
        if task.status == TaskStatus.PENDING_APPROVAL:
            raise HTTPException(status_code=400, detail="Task is awaiting admin approval")
        if task.status == TaskStatus.REJECTED:
            raise HTTPException(status_code=400, detail="Task was rejected by admin")

    def update_task(self, task_id: int, data: dict, user: User | None = None, employee_owned: bool = False) -> Task:
        task = self.db.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if employee_owned:
            self._ensure_task_actionable(task)
        previous = {"status": task.status, "progress": task.progress}
        for field in ["title", "description", "priority", "due_date", "estimated_minutes", "status", "progress", "notes"]:
            if field in data and data[field] is not None:
                setattr(task, field, data[field])
        if data.get("status") == TaskStatus.IN_PROGRESS and not task.started_at:
            task.started_at = datetime.utcnow()
        if data.get("status") == TaskStatus.COMPLETED:
            task.completed_at = datetime.utcnow()
            task.progress = 100
        if task.due_date and task.due_date < date.today() and task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            task.status = TaskStatus.OVERDUE
            self.exceptions.create(
                task.assigned_employee_id,
                ExceptionType.OVERDUE_TASK,
                f"Overdue task: {task.title}",
                f"Task was due on {task.due_date.isoformat()}",
                "task",
                task.id,
            )
        if user:
            self.audit.log("task_updated", user, "task", task.id, previous, {"status": task.status, "progress": task.progress})
        return task

    def toggle_checklist_item(self, item_id: int, completed: bool, user: User | None = None):
        item = self.db.get(TaskChecklistItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Checklist item not found")
        task = self.db.get(Task, item.task_id)
        if task:
            self._ensure_task_actionable(task)
        item.is_completed = completed
        item.completed_at = datetime.utcnow() if completed else None
        task = self.db.get(Task, item.task_id)
        if task:
            items = self.db.query(TaskChecklistItem).filter(TaskChecklistItem.task_id == task.id).all()
            if items:
                task.progress = int(sum(1 for i in items if i.is_completed) / len(items) * 100)
        return item

    def start_timer(self, task_id: int, employee_id: int) -> TaskTimeLog:
        task = self.db.get(Task, task_id)
        if task:
            self._ensure_task_actionable(task)
        log = TaskTimeLog(task_id=task_id, employee_id=employee_id, started_at=datetime.utcnow())
        self.db.add(log)
        if task and task.status == TaskStatus.NOT_STARTED:
            task.status = TaskStatus.IN_PROGRESS
            task.started_at = datetime.utcnow()
        return log

    def stop_timer(self, log_id: int, employee_id: int | None = None) -> TaskTimeLog:
        log = self.db.get(TaskTimeLog, log_id)
        if not log or log.ended_at:
            raise HTTPException(status_code=400, detail="Invalid time log")
        if employee_id is not None and log.employee_id != employee_id:
            raise HTTPException(status_code=403, detail="Not your time log")
        now = datetime.utcnow()
        log.ended_at = now
        log.duration_minutes = int((now - log.started_at).total_seconds() // 60)
        task = self.db.get(Task, log.task_id)
        if task:
            total = (
                self.db.query(func.coalesce(func.sum(TaskTimeLog.duration_minutes), 0))
                .filter(TaskTimeLog.task_id == task.id, TaskTimeLog.ended_at.isnot(None))
                .scalar()
                or 0
            )
            task.actual_minutes = int(total) + (log.duration_minutes or 0)
        return log

    def list_tasks(self, employee_id: int | None = None, status: str | None = None, limit: int | None = 500):
        q = self.db.query(Task).options(selectinload(Task.checklist_items))
        if employee_id:
            q = q.filter(Task.assigned_employee_id == employee_id)
        if status:
            q = q.filter(Task.status == status)
        q = q.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        if limit:
            q = q.limit(limit)
        return q.all()

    def dashboard_stats(self, employee_id: int | None = None) -> dict:
        today = date.today()
        q = self.db.query(
            func.count(Task.id),
            func.sum(case((Task.status == TaskStatus.OVERDUE, 1), else_=0)),
            func.sum(case((Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.PENDING_APPROVAL, TaskStatus.REJECTED]), 1), else_=0)),
            func.sum(case((and_(Task.completed_at.isnot(None), func.date(Task.completed_at) == today), 1), else_=0)),
            func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)),
            func.sum(case((Task.status == TaskStatus.IN_PROGRESS, 1), else_=0)),
        )
        if employee_id:
            q = q.filter(Task.assigned_employee_id == employee_id)
        total, overdue, active, completed_today, completed, in_progress = q.one()
        return {
            "total": int(total or 0),
            "completed": int(completed or 0),
            "overdue": int(overdue or 0),
            "total_active": int(active or 0),
            "completed_today": int(completed_today or 0),
            "in_progress": int(in_progress or 0),
        }

    def task_summary(self, employee_id: int) -> dict:
        today = date.today()
        row = (
            self.db.query(
                func.count(Task.id),
                func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)),
                func.sum(case((Task.status.in_([TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED]), 1), else_=0)),
                func.sum(case((Task.status == TaskStatus.OVERDUE, 1), else_=0)),
                func.sum(case((and_(Task.due_date == today, Task.status != TaskStatus.COMPLETED), 1), else_=0)),
            )
            .filter(Task.assigned_employee_id == employee_id)
            .one()
        )
        total, completed, pending, overdue, due_today = row
        return {
            "total": int(total or 0),
            "completed": int(completed or 0),
            "pending": int(pending or 0),
            "overdue": int(overdue or 0),
            "due_today": int(due_today or 0),
        }
