import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_db = Path(tempfile.gettempdir()) / "vectorise-team-tests.db"
if _db.exists():
    _db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_db.as_posix()}"
os.environ["SEED_DATABASE"] = "false"
os.environ["ENABLE_SYNC_SCHEDULER"] = "false"
os.environ["ENVIRONMENT"] = "test"

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.chat import ChatConversation, ChatMessage, ChatParticipant
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.user import User
from app.services.auth import create_access_token, hash_password


def _headers(person: dict) -> dict[str, str]:
    token = create_access_token(person["email"], person["role"], person["employee_id"], person["token_version"])
    return {"Authorization": f"Bearer {token}"}


class TeamAndReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        db = SessionLocal()
        try:
            cls.admin = _user(db, "Admin User", "EMP9001", "admin@team.test", "admin")
            cls.ada = _user(db, "Ada Lead", "EMP9002", "ada@team.test", "employee")
            cls.ben = _user(db, "Ben Report", "EMP9003", "ben@team.test", "employee")
            cls.cam = _user(db, "Cam Outside", "EMP9004", "cam@team.test", "employee")
            cls.dee = _user(db, "Dee Cycle", "EMP9005", "dee@team.test", "employee")
            cls.eve = _user(db, "Eve Cycle", "EMP9006", "eve@team.test", "employee")
            cls.fay = _user(db, "Fay Cycle", "EMP9007", "fay@team.test", "employee")
            cls.ada_note = Notification(
                user_id=cls.ada.id, title="Ada new", message="Unread for Ada", is_read=False
            )
            cls.ada_old = Notification(
                user_id=cls.ada.id,
                title="Ada old",
                message="Older unread",
                is_read=False,
                created_at=datetime.utcnow() - timedelta(days=10),
            )
            cls.ben_note = Notification(
                user_id=cls.ben.id, title="Ben new", message="Unread for Ben", is_read=False
            )
            db.add_all([cls.ada_note, cls.ada_old, cls.ben_note])
            conversation = ChatConversation(title="Ada and Ben")
            db.add(conversation)
            db.flush()
            db.add_all([
                ChatParticipant(conversation_id=conversation.id, user_id=cls.ada.id),
                ChatParticipant(conversation_id=conversation.id, user_id=cls.ben.id),
                ChatMessage(conversation_id=conversation.id, sender_id=cls.ben.id, body="Hello Ada"),
                ChatMessage(conversation_id=conversation.id, sender_id=cls.ada.id, body="Hello Ben"),
            ])
            cls.ids = {
                name: {"user_id": user.id, "employee_id": user.employee_id, "email": user.email, "role": user.role, "token_version": user.token_version}
                for name, user in {
                    "admin": cls.admin,
                    "ada": cls.ada,
                    "ben": cls.ben,
                    "cam": cls.cam,
                    "dee": cls.dee,
                    "eve": cls.eve,
                    "fay": cls.fay,
                }.items()
            }
            db.commit()
            cls.admin_headers = _headers(cls.ids["admin"])
            cls.ada_headers = _headers(cls.ids["ada"])
            cls.ben_headers = _headers(cls.ids["ben"])
            cls.cam_headers = _headers(cls.ids["cam"])
            cls.fay_headers = _headers(cls.ids["fay"])
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_mark_all_reads_only_the_current_user(self):
        ada = self.client.post("/api/notifications/read-all", headers=self.ada_headers)
        self.assertEqual(ada.status_code, 200)
        self.assertGreaterEqual(ada.json()["updated"], 2)
        self.assertEqual(self.client.get("/api/notifications/unread-count", headers=self.ada_headers).json()["count"], 0)
        db = SessionLocal()
        try:
            ada_old = db.query(Notification).filter(Notification.title == "Ada old").one()
            ben_note = db.query(Notification).filter(Notification.title == "Ben new").one()
            self.assertTrue(ada_old.is_read)
            self.assertFalse(ben_note.is_read)
        finally:
            db.close()

        ada_chat = self.client.post("/api/chat/read-all", headers=self.ada_headers)
        self.assertEqual(ada_chat.status_code, 200)
        self.assertEqual(ada_chat.json()["updated"], 1)
        self.assertEqual(self.client.get("/api/chat/unread-count", headers=self.ada_headers).json()["count"], 0)
        self.assertEqual(self.client.get("/api/chat/unread-count", headers=self.ben_headers).json()["count"], 1)

    def test_hierarchy_rules_and_team_permissions(self):
        self_assign = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["ada"]["employee_id"], "employee_id": self.ids["ada"]["employee_id"]},
        )
        self.assertEqual(self_assign.status_code, 400)
        self.assertIn("own team lead", self_assign.json()["detail"])

        first = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["ada"]["employee_id"], "employee_id": self.ids["ben"]["employee_id"]},
        )
        self.assertEqual(first.status_code, 200, first.text)
        ada_team = self.client.get("/api/team/me", headers=self.ada_headers)
        self.assertEqual(ada_team.status_code, 200, ada_team.text)
        self.assertEqual([person["name"] for person in ada_team.json()["direct_reports"]], ["Ben Report"])
        self.assertEqual(self.client.get("/api/team/me", headers=self.ben_headers).json()["direct_reports"], [])
        duplicate = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["ada"]["employee_id"], "employee_id": self.ids["ben"]["employee_id"]},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already assigned", duplicate.json()["detail"])

        self.assertEqual(
            self.client.post(
                "/api/admin/team-assignments",
                headers=self.admin_headers,
                json={"team_lead_id": self.ids["dee"]["employee_id"], "employee_id": self.ids["eve"]["employee_id"]},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/team-assignments",
                headers=self.admin_headers,
                json={"team_lead_id": self.ids["eve"]["employee_id"], "employee_id": self.ids["fay"]["employee_id"]},
            ).status_code,
            200,
        )
        reverse = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["eve"]["employee_id"], "employee_id": self.ids["dee"]["employee_id"]},
        )
        self.assertEqual(reverse.status_code, 400)
        self.assertIn("circular", reverse.json()["detail"])
        longer = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["fay"]["employee_id"], "employee_id": self.ids["dee"]["employee_id"]},
        )
        self.assertEqual(longer.status_code, 400)
        self.assertIn("circular", longer.json()["detail"])

        ben_leads_fay = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["ben"]["employee_id"], "employee_id": self.ids["fay"]["employee_id"]},
        )
        self.assertEqual(ben_leads_fay.status_code, 200, ben_leads_fay.text)
        fay = self.client.get(f"/api/team/people/{self.ids['fay']['employee_id']}", headers=self.fay_headers)
        self.assertEqual(fay.status_code, 200)
        self.assertEqual(sorted(person["name"] for person in fay.json()["team_leads"]), ["Ben Report", "Eve Cycle"])
        self.assertNotIn("managers", fay.json())
        eve_headers = _headers(self.ids["eve"])
        eve_sees_fay = self.client.get(f"/api/team/people/{self.ids['fay']['employee_id']}", headers=eve_headers)
        self.assertEqual(eve_sees_fay.status_code, 200)
        self.assertEqual(eve_sees_fay.json()["relationship"], "report")
        self.assertEqual(eve_sees_fay.json()["team_leads"], [])
        self.assertEqual(eve_sees_fay.json()["direct_reports"], [])
        fay_sees_eve = self.client.get(f"/api/team/people/{self.ids['eve']['employee_id']}", headers=self.fay_headers)
        self.assertEqual(fay_sees_eve.status_code, 200)
        self.assertEqual(fay_sees_eve.json()["relationship"], "team_lead")
        self.assertEqual(fay_sees_eve.json()["employee"]["name"], "Eve Cycle")
        self.assertEqual(fay_sees_eve.json()["team_leads"], [])
        self.assertEqual(fay_sees_eve.json()["direct_reports"], [])

        profile = self.client.get(f"/api/team/people/{self.ids['ben']['employee_id']}", headers=self.ben_headers)
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["team_leads"][0]["name"], "Ada Lead")
        hidden = self.client.get(f"/api/team/people/{self.ids['ben']['employee_id']}", headers=self.cam_headers)
        self.assertEqual(hidden.status_code, 403)

        created = self.client.post(
            f"/api/team/reports/{self.ids['ben']['employee_id']}/tasks",
            headers=self.ada_headers,
            json={"title": "Prepare the weekly note", "assigned_employee_id": self.ids["ben"]["employee_id"], "priority": "medium"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        task_id = created.json()["id"]
        denied = self.client.post(
            f"/api/team/reports/{self.ids['ben']['employee_id']}/tasks",
            headers=self.cam_headers,
            json={"title": "Should fail", "assigned_employee_id": self.ids["ben"]["employee_id"], "priority": "medium"},
        )
        self.assertEqual(denied.status_code, 403)

        review = self.client.post(
            f"/api/team/tasks/{task_id}/reviews",
            headers=self.ada_headers,
            json={"rating": 4, "comments": "Clear and complete", "status": "approved"},
        )
        self.assertEqual(review.status_code, 200, review.text)
        outsider_review = self.client.post(
            f"/api/team/tasks/{task_id}/reviews",
            headers=self.cam_headers,
            json={"rating": 1, "comments": "No", "status": "needs_changes"},
        )
        self.assertEqual(outsider_review.status_code, 403)
        docs = self.client.get(f"/api/team/tasks/{task_id}/documents", headers=self.ada_headers)
        self.assertEqual(docs.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/employee/tasks/{task_id}/documents", headers=self.cam_headers).status_code,
            403,
        )
        evaluation = self.client.post(
            f"/api/team/reports/{self.ids['ben']['employee_id']}/evaluations",
            headers=self.ada_headers,
            json={
                "employee_id": self.ids["ben"]["employee_id"],
                "period_start": "2026-11-01",
                "period_end": "2026-11-14",
                "score": 88,
                "comments": "Strong week",
            },
        )
        self.assertEqual(evaluation.status_code, 200, evaluation.text)
        self.assertEqual(
            self.client.post(
                f"/api/team/reports/{self.ids['ben']['employee_id']}/evaluations",
                headers=self.cam_headers,
                json={
                    "employee_id": self.ids["ben"]["employee_id"],
                    "period_start": "2026-11-01",
                    "period_end": "2026-11-14",
                    "score": 10,
                },
            ).status_code,
            403,
        )
        added = self.client.post(
            "/api/admin/team-assignments",
            headers=self.admin_headers,
            json={"team_lead_id": self.ids["ada"]["employee_id"], "employee_id": self.ids["cam"]["employee_id"]},
        )
        self.assertEqual(added.status_code, 200, added.text)
        both = self.client.get("/api/team/me", headers=self.ada_headers)
        self.assertEqual(sorted(person["name"] for person in both.json()["direct_reports"]), ["Ben Report", "Cam Outside"])
        removed = self.client.delete(
            f"/api/admin/team-assignments?team_lead_id={self.ids['ada']['employee_id']}&employee_id={self.ids['cam']['employee_id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        after = self.client.get("/api/team/me", headers=self.ada_headers)
        self.assertEqual([person["name"] for person in after.json()["direct_reports"]], ["Ben Report"])
        self.assertEqual(self.client.get("/api/team/me", headers=self.cam_headers).json()["direct_reports"], [])


def _user(db, name: str, code: str, email: str, role: str) -> User:
    employee = None
    if role != "admin":
        employee = Employee(name=name, employee_code=code, email=email, role=role, status="active")
        db.add(employee)
        db.flush()
    user = User(
        email=email,
        hashed_password=hash_password("pass1234"),
        role=role,
        employee_id=employee.id if employee else None,
        token_version=0,
    )
    db.add(user)
    db.flush()
    return user


if __name__ == "__main__":
    unittest.main()
