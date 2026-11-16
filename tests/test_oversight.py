import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_db = Path(tempfile.gettempdir()) / "vectorise-oversight-tests.db"
if _db.exists():
    _db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_db.as_posix()}"
os.environ["SEED_DATABASE"] = "false"
os.environ["ENABLE_SYNC_SCHEDULER"] = "false"
os.environ["ENVIRONMENT"] = "test"

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.employee import Employee
from app.models.task import Task
from app.models.user import User
from app.services.activity_log import ActivityLogService, run_backfill, utc_today, utcnow
from app.services.auth import create_access_token, hash_password
from app.services.hierarchy import HierarchyService


def _headers(person: dict) -> dict[str, str]:
    token = create_access_token(person["email"], person["role"], person["employee_id"], person["token_version"])
    return {"Authorization": f"Bearer {token}"}


def _person(db, name, code, email, role="employee"):
    employee = Employee(name=name, employee_code=code, email=email, role=role, status="active", job_title="Specialist")
    db.add(employee)
    db.flush()
    user = User(email=email, hashed_password=hash_password("pass1234"), role=role, employee_id=employee.id, token_version=0)
    db.add(user)
    db.flush()
    return {"id": user.id, "email": email, "role": role, "employee_id": employee.id, "token_version": 0, "name": name}


class OversightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        db = SessionLocal()
        try:
            admin_employee = None
            admin = User(email="oversight-admin@test", hashed_password=hash_password("pass1234"), role="admin", employee_id=None, token_version=0)
            db.add(admin)
            db.flush()
            cls.admin = {"id": admin.id, "email": admin.email, "role": "admin", "employee_id": None, "token_version": 0, "name": "Admin"}
            cls.manager = _person(db, "Morgan Manager", "OV001", "morgan@test")
            cls.lead_a = _person(db, "Ada Lead", "OV002", "ada-ov@test")
            cls.lead_b = _person(db, "Ben Lead", "OV003", "ben-ov@test")
            cls.member = _person(db, "Mina Member", "OV004", "mina@test")
            cls.other = _person(db, "Omar Other", "OV005", "omar@test")
            cls.solo = _person(db, "Sam Solo", "OV006", "sam@test")
            hierarchy = HierarchyService(db)
            hierarchy.assign(cls.manager["employee_id"], cls.lead_a["employee_id"], admin.id)
            hierarchy.assign(cls.manager["employee_id"], cls.lead_b["employee_id"], admin.id)
            hierarchy.assign(cls.lead_a["employee_id"], cls.member["employee_id"], admin.id)
            hierarchy.assign(cls.lead_b["employee_id"], cls.member["employee_id"], admin.id)
            hierarchy.assign(cls.lead_b["employee_id"], cls.other["employee_id"], admin.id)
            today = utc_today()
            cls.overdue = _task(db, "Overdue brief", cls.member["employee_id"], cls.lead_a["id"], today - timedelta(days=3), "in_progress")
            cls.on_time = _task(db, "On time note", cls.member["employee_id"], cls.lead_a["id"], today - timedelta(days=2), "completed", today - timedelta(days=2))
            cls.late = _task(db, "Late note", cls.member["employee_id"], cls.lead_a["id"], today - timedelta(days=5), "completed", today - timedelta(days=1))
            cls.no_due = _task(db, "No deadline", cls.member["employee_id"], cls.lead_a["id"], None, "completed", today)
            cls.pending = _task(db, "Needs review", cls.member["employee_id"], cls.lead_a["id"], None, "completed", utcnow() - timedelta(days=5))
            cls.stuck = _task(db, "Blocked work", cls.other["employee_id"], cls.lead_b["id"], today + timedelta(days=2), "blocked")
            cls.admin_task = _task(db, "Admin assigned", cls.member["employee_id"], admin.id, today - timedelta(days=1), "in_progress")
            db.commit()
            cls.admin_headers = _headers(cls.admin)
            cls.manager_headers = _headers(cls.manager)
            cls.lead_a_headers = _headers(cls.lead_a)
            cls.lead_b_headers = _headers(cls.lead_b)
            cls.member_headers = _headers(cls.member)
            cls.solo_headers = _headers(cls.solo)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_assignment_and_removal_write_one_row_and_rollback_writes_none(self):
        db = SessionLocal()
        try:
            before = db.query(ActivityLog).filter(ActivityLog.action_type == "team_lead_assigned").count()
            actor = db.get(User, self.admin["id"])
            hierarchy = HierarchyService(db)
            hierarchy.assign(self.lead_a["employee_id"], self.solo["employee_id"], actor.id)
            db.commit()
            added = db.query(ActivityLog).filter(ActivityLog.action_type == "team_lead_assigned", ActivityLog.target_employee_id == self.solo["employee_id"]).all()
            self.assertEqual(len(added), 1)
            self.assertEqual(added[0].team_lead_id, self.lead_a["employee_id"])
            hierarchy.remove(self.lead_a["employee_id"], self.solo["employee_id"], actor)
            db.commit()
            removed = db.query(ActivityLog).filter(ActivityLog.action_type == "team_lead_removed", ActivityLog.target_employee_id == self.solo["employee_id"]).all()
            self.assertEqual(len(removed), 1)
            self.assertGreaterEqual(db.query(ActivityLog).filter(ActivityLog.action_type == "team_lead_assigned").count(), before)
            ActivityLogService(db).record(action_type="login", entity_type="user", entity_id=self.admin["id"], actor_id=self.admin["id"], metadata={"actor_name": "Rollback"})
            db.rollback()
        finally:
            db.close()
        check = SessionLocal()
        try:
            leaked = check.query(ActivityLog).filter(ActivityLog.metadata_json["actor_name"].as_string() == "Rollback").count()
            self.assertEqual(leaked, 0)
        finally:
            check.close()

    def test_backfill_is_idempotent_and_last_active_is_throttled(self):
        db = SessionLocal()
        try:
            first = run_backfill(db)
            db.commit()
            second = run_backfill(db)
            db.commit()
            self.assertGreater(first, 0)
            self.assertEqual(second, 0)
            user = db.get(User, self.member["id"])
            service = ActivityLogService(db)
            self.assertTrue(service.touch_last_active(user, utcnow()))
            stamped = db.get(User, self.member["id"]).last_active_at
            self.assertFalse(service.touch_last_active(db.get(User, self.member["id"]), stamped + timedelta(minutes=5)))
            self.assertEqual(db.get(User, self.member["id"]).last_active_at, stamped)
        finally:
            db.close()

    def test_status_change_writes_one_row(self):
        updated = self.client.put(
            f"/api/hrm/tasks/{self.stuck}",
            headers=self.admin_headers,
            json={"status": "in_progress"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        db = SessionLocal()
        try:
            rows = db.query(ActivityLog).filter(ActivityLog.entity_id == self.stuck, ActivityLog.action_type == "task_status_changed").all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].metadata_json["new_status"], "in_progress")
        finally:
            db.close()

    def test_metrics_and_scope(self):
        teams = self.client.get("/api/oversight/teams?page_size=50", headers=self.admin_headers)
        self.assertEqual(teams.status_code, 200, teams.text)
        ada = next(item for item in teams.json()["items"] if item["name"] == "Ada Lead")
        self.assertEqual(ada["tasks_assigned"], 5)
        self.assertGreaterEqual(ada["overdue_tasks"], 2)
        self.assertEqual(ada["on_time_rate"], 0.5)
        self.assertGreaterEqual(ada["pending_reviews"], 1)
        ben = next(item for item in teams.json()["items"] if item["name"] == "Ben Lead")
        self.assertGreaterEqual(ben["stuck_tasks"], 1)
        summary = self.client.get("/api/oversight/summary", headers=self.admin_headers)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertGreaterEqual(summary.json()["overdue_tasks"], 2)
        self.assertGreaterEqual(summary.json()["employees_without_lead"], 1)
        denied = self.client.get("/api/oversight/summary", headers=self.solo_headers)
        self.assertEqual(denied.status_code, 403)
        other_team = self.client.get(f"/api/oversight/teams/{self.lead_b['employee_id']}", headers=self.lead_a_headers)
        self.assertEqual(other_team.status_code, 403)
        own = self.client.get(f"/api/oversight/teams/{self.lead_a['employee_id']}", headers=self.lead_a_headers)
        self.assertEqual(own.status_code, 200, own.text)
        managed = self.client.get(f"/api/oversight/employees/{self.member['employee_id']}", headers=self.manager_headers)
        self.assertEqual(managed.status_code, 200, managed.text)
        hidden = self.client.get(f"/api/oversight/employees/{self.other['employee_id']}", headers=self.lead_a_headers)
        self.assertEqual(hidden.status_code, 403)
        self_view = self.client.get(f"/api/oversight/employees/{self.solo['employee_id']}", headers=self.solo_headers)
        self.assertEqual(self_view.status_code, 200, self_view.text)

    def test_team_table_query_count_stays_small(self):
        statements = {"count": 0}

        def count_queries(*_args, **_kwargs):
            statements["count"] += 1

        event.listen(engine, "before_cursor_execute", count_queries)
        try:
            response = self.client.get("/api/oversight/teams?page_size=25", headers=self.admin_headers)
        finally:
            event.remove(engine, "before_cursor_execute", count_queries)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLess(statements["count"], 25)

    def test_export_escapes_formulas_and_hides_other_teams(self):
        exported = self.client.get("/api/oversight/export/teams.csv", headers=self.lead_a_headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("Ada Lead", exported.text)
        self.assertNotIn("Omar Other", exported.text)
        self.assertNotIn("Ben Lead", exported.text)
        from app.api.oversight_routes import _csv_cell
        self.assertTrue(_csv_cell("=1+1").startswith("'"))
        self.assertTrue(_csv_cell("+cmd").startswith("'"))
        self.assertEqual(_csv_cell("Ada Lead"), "Ada Lead")

    def test_permission_matrix_hides_other_teams(self):
        ada = self.lead_a["employee_id"]
        ben = self.lead_b["employee_id"]
        mina = self.member["employee_id"]
        omar = self.other["employee_id"]
        cases = [
            ("/api/oversight/summary", self.admin_headers, 200),
            ("/api/oversight/summary", self.manager_headers, 200),
            ("/api/oversight/summary", self.lead_a_headers, 200),
            ("/api/oversight/summary", self.member_headers, 403),
            ("/api/oversight/teams", self.lead_b_headers, 200),
            ("/api/oversight/teams", self.solo_headers, 403),
            (f"/api/oversight/teams/{ada}", self.admin_headers, 200),
            (f"/api/oversight/teams/{ada}", self.manager_headers, 200),
            (f"/api/oversight/teams/{ada}", self.lead_a_headers, 200),
            (f"/api/oversight/teams/{ada}", self.lead_b_headers, 403),
            (f"/api/oversight/teams/{ben}", self.lead_a_headers, 403),
            (f"/api/oversight/teams/{ada}/tasks", self.member_headers, 403),
            (f"/api/oversight/teams/{ada}/reviews", self.lead_b_headers, 403),
            (f"/api/oversight/teams/{ada}/activity", self.lead_a_headers, 200),
            (f"/api/oversight/employees/{mina}", self.lead_a_headers, 200),
            (f"/api/oversight/employees/{mina}", self.lead_b_headers, 200),
            (f"/api/oversight/employees/{mina}", self.member_headers, 200),
            (f"/api/oversight/employees/{omar}", self.lead_a_headers, 403),
            (f"/api/oversight/employees/{omar}", self.member_headers, 403),
            (f"/api/oversight/employees/{ada}", self.solo_headers, 403),
            ("/api/oversight/hierarchy", self.manager_headers, 200),
            ("/api/oversight/hierarchy", self.member_headers, 403),
            ("/api/oversight/activity", self.lead_a_headers, 200),
            ("/api/oversight/activity", self.member_headers, 403),
            ("/api/oversight/trends", self.solo_headers, 403),
            ("/api/oversight/export/teams.csv", self.member_headers, 403),
            (f"/api/oversight/export/teams/{ben}/tasks.csv", self.lead_a_headers, 403),
            ("/api/oversight/export/activity.csv", self.member_headers, 403),
        ]
        for path, headers, expected in cases:
            response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, expected, f"{path} -> {response.status_code} {response.text}")
        own_feed = self.client.get("/api/oversight/activity?page_size=100", headers=self.lead_a_headers)
        self.assertEqual(own_feed.status_code, 200, own_feed.text)
        self.assertNotIn("Omar Other", own_feed.text)
        manager_tree = self.client.get("/api/oversight/hierarchy", headers=self.manager_headers)
        self.assertIn("Mina Member", manager_tree.text)
        self.assertNotIn("Sam Solo", manager_tree.text)

    def test_alert_notifies_once_and_again_after_the_condition_clears(self):
        from app.models.notification import Notification
        from app.services.oversight_alerts import run_oversight_alerts

        db = SessionLocal()
        original = None
        try:
            first = run_oversight_alerts(db)
            db.commit()
            second = run_oversight_alerts(db)
            db.commit()
            self.assertGreater(first, 0)
            self.assertEqual(second, 0)
            task = db.get(Task, self.overdue)
            original = task.due_date
            task.due_date = utc_today() + timedelta(days=10)
            db.commit()
            run_oversight_alerts(db)
            db.commit()
            task.due_date = utc_today() - timedelta(days=10)
            db.commit()
            third = run_oversight_alerts(db)
            db.commit()
            self.assertGreaterEqual(third, 1)
            self.assertGreater(db.query(Notification).filter(Notification.title == "Task overdue").count(), 0)
        finally:
            if original is not None:
                task = db.get(Task, self.overdue)
                task.due_date = original
                db.commit()
            db.close()


def _task(db, title, employee_id, assigned_by, due, status, completed_at=None):
    completed = completed_at
    if isinstance(completed_at, datetime):
        completed = completed_at
    elif completed_at is not None:
        completed = datetime.combine(completed_at, datetime.min.time())
    task = Task(
        title=title,
        assigned_employee_id=employee_id,
        assigned_by_id=assigned_by,
        due_date=due,
        status=status,
        completed_at=completed if status == "completed" else None,
        updated_at=utcnow(),
    )
    db.add(task)
    db.flush()
    return task.id


if __name__ == "__main__":
    unittest.main()
