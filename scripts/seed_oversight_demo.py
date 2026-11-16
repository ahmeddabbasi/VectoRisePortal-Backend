"""Create a local oversight demo. Refuses to run when ENVIRONMENT is production.

Usage, from the backend folder, against the local SQLite database:
  python scripts/seed_oversight_demo.py
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SEED_DATABASE", "false")
os.environ.setdefault("ENABLE_SYNC_SCHEDULER", "false")

from app.database import SessionLocal, init_db
from app.models.employee import Employee
from app.models.task import Task
from app.models.user import User
from app.services.activity_log import utc_today, utcnow
from app.services.auth import hash_password
from app.services.hierarchy import HierarchyService


def main() -> None:
    if os.environ.get("ENVIRONMENT", "").lower() != "development":
        raise SystemExit("Refusing to seed demo data unless ENVIRONMENT=development.")
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "oversight.demo.admin@vectoriseinc.dev").first():
            print("Demo people already exist. Sign in with the emails below and password DemoPass1.")
            return
        admin = User(email="oversight.demo.admin@vectoriseinc.dev", hashed_password=hash_password("DemoPass1"), role="admin", token_version=0)
        db.add(admin)
        db.flush()

        def person(name, code, email, title):
            employee = Employee(name=name, employee_code=code, email=email, role="employee", status="active", job_title=title)
            db.add(employee)
            db.flush()
            user = User(email=email, hashed_password=hash_password("DemoPass1"), role="employee", employee_id=employee.id, token_version=0)
            db.add(user)
            db.flush()
            return employee, user

        manager, _manager_user = person("Demo Manager", "DEM001", "oversight.demo.manager@vectoriseinc.dev", "Director")
        lead_a, lead_a_user = person("Demo Lead Ada", "DEM002", "oversight.demo.ada@vectoriseinc.dev", "Team lead")
        lead_b, lead_b_user = person("Demo Lead Ben", "DEM003", "oversight.demo.ben@vectoriseinc.dev", "Team lead")
        member, _member_user = person("Demo Member Mina", "DEM004", "oversight.demo.mina@vectoriseinc.dev", "Specialist")
        other, _other_user = person("Demo Member Omar", "DEM005", "oversight.demo.omar@vectoriseinc.dev", "Specialist")
        solo, _solo_user = person("Demo Solo Sam", "DEM006", "oversight.demo.sam@vectoriseinc.dev", "Specialist")
        hierarchy = HierarchyService(db)
        hierarchy.assign(manager.id, lead_a.id, admin.id)
        hierarchy.assign(manager.id, lead_b.id, admin.id)
        hierarchy.assign(lead_a.id, member.id, admin.id)
        hierarchy.assign(lead_b.id, member.id, admin.id)
        hierarchy.assign(lead_b.id, other.id, admin.id)
        today = utc_today()
        db.add_all([
            Task(title="Overdue client brief", assigned_employee_id=member.id, assigned_by_id=lead_a_user.id, due_date=today - timedelta(days=4), status="in_progress"),
            Task(title="Finished on time", assigned_employee_id=member.id, assigned_by_id=lead_a_user.id, due_date=today - timedelta(days=2), status="completed", completed_at=utcnow() - timedelta(days=3)),
            Task(title="Waiting for review", assigned_employee_id=member.id, assigned_by_id=lead_a_user.id, due_date=today - timedelta(days=1), status="completed", completed_at=utcnow() - timedelta(days=6)),
            Task(title="Blocked rollout", assigned_employee_id=other.id, assigned_by_id=lead_b_user.id, due_date=today + timedelta(days=3), status="blocked"),
        ])
        db.commit()
        print("Demo ready. Password for every account: DemoPass1")
        print("Admin: oversight.demo.admin@vectoriseinc.dev")
        print("Manager: oversight.demo.manager@vectoriseinc.dev")
        print("Leads: oversight.demo.ada@vectoriseinc.dev and oversight.demo.ben@vectoriseinc.dev")
        print("Member with two leads: oversight.demo.mina@vectoriseinc.dev")
        print("No team lead: oversight.demo.sam@vectoriseinc.dev")
        print(f"Unused local record: {solo.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
