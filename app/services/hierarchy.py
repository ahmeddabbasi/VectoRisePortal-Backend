from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.team_lead import TeamLeadAssignment
from app.models.user import User


class HierarchyService:
    def __init__(self, db: Session):
        self.db = db

    def leads(self, team_lead_id: int, employee_id: int) -> bool:
        return (
            self.db.query(TeamLeadAssignment)
            .filter(
                TeamLeadAssignment.team_lead_id == team_lead_id,
                TeamLeadAssignment.employee_id == employee_id,
            )
            .first()
            is not None
        )

    def report_ids(self, team_lead_id: int) -> list[int]:
        rows = (
            self.db.query(TeamLeadAssignment.employee_id)
            .filter(TeamLeadAssignment.team_lead_id == team_lead_id)
            .all()
        )
        return [row[0] for row in rows]

    def lead_ids(self, employee_id: int) -> list[int]:
        rows = (
            self.db.query(TeamLeadAssignment.team_lead_id)
            .filter(TeamLeadAssignment.employee_id == employee_id)
            .all()
        )
        return [row[0] for row in rows]

    def can_view_task(self, user: User, task) -> bool:
        if user.role == "admin" or user.can_review_tasks:
            return True
        if not user.employee_id or task is None:
            return False
        if task.assigned_employee_id == user.employee_id:
            return True
        return self.leads(user.employee_id, task.assigned_employee_id)

    def require_leads(self, user: User, employee_id: int) -> None:
        if user.role == "admin":
            return
        if not user.employee_id or not self.leads(user.employee_id, employee_id):
            raise HTTPException(status_code=403, detail="You can only do this for employees you lead")

    def can_view_person(self, user: User, employee_id: int) -> bool:
        if user.role == "admin" or user.employee_id == employee_id:
            return True
        if not user.employee_id:
            return False
        return self.leads(user.employee_id, employee_id) or self.leads(employee_id, user.employee_id)

    def creates_cycle(self, team_lead_id: int, employee_id: int) -> bool:
        stack = [employee_id]
        seen: set[int] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for report_id in self.report_ids(current):
                if report_id == team_lead_id:
                    return True
                stack.append(report_id)
        return False

    def assign(self, team_lead_id: int, employee_id: int, created_by: int | None) -> TeamLeadAssignment:
        if team_lead_id == employee_id:
            raise HTTPException(status_code=400, detail="An employee cannot be their own team lead")
        if not self.db.get(Employee, team_lead_id) or not self.db.get(Employee, employee_id):
            raise HTTPException(status_code=404, detail="Employee not found")
        if self.leads(team_lead_id, employee_id):
            raise HTTPException(status_code=400, detail="That team lead is already assigned to this employee")
        if self.creates_cycle(team_lead_id, employee_id):
            raise HTTPException(status_code=400, detail="That assignment would create a circular team")
        row = TeamLeadAssignment(
            team_lead_id=team_lead_id,
            employee_id=employee_id,
            created_by=created_by,
        )
        self.db.add(row)
        self.db.flush()
        from app.services.activity_log import ActivityLogService

        actor = self.db.get(User, created_by) if created_by else None
        ActivityLogService(self.db).team_assigned(actor, team_lead_id, employee_id, row.id)
        return row

    def remove(self, team_lead_id: int, employee_id: int, actor: User | None = None) -> None:
        row = (
            self.db.query(TeamLeadAssignment)
            .filter(
                TeamLeadAssignment.team_lead_id == team_lead_id,
                TeamLeadAssignment.employee_id == employee_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="That assignment was not found")
        from app.services.activity_log import ActivityLogService

        ActivityLogService(self.db).team_removed(actor, team_lead_id, employee_id, row.id)
        self.db.delete(row)

    def people(self, employee_ids: list[int]) -> list[dict]:
        if not employee_ids:
            return []
        rows = self.db.query(Employee).filter(Employee.id.in_(employee_ids)).order_by(Employee.name).all()
        return [{"id": row.id, "name": row.name, "job_title": row.job_title} for row in rows]

    def summary(self, employee_id: int) -> dict:
        return {
            "team_leads": self.people(self.lead_ids(employee_id)),
            "direct_reports": self.people(self.report_ids(employee_id)),
        }

    def visible_profile(self, user: User, employee: Employee) -> dict:
        person = {"id": employee.id, "name": employee.name, "job_title": employee.job_title}
        if user.role == "admin" or user.employee_id == employee.id:
            return {"employee": person, "relationship": "self", **self.summary(employee.id)}
        if user.employee_id and self.leads(employee.id, user.employee_id):
            relationship = "team_lead"
        else:
            relationship = "report"
        return {"employee": person, "relationship": relationship, "team_leads": [], "direct_reports": []}
