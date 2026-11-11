from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.text_guard import PROFILE_FILE
from app.models.activity import Activity
from app.models.announcement import Announcement
from app.models.attendance_record import AttendanceRecord
from app.models.chat import ChatMessage, ChatParticipant
from app.models.data_source import DataSource
from app.models.employee import Employee
from app.models.enums import UserRole
from app.models.exception_record import ExceptionRecord
from app.models.hr_evaluation import HREvaluation
from app.models.lead import Lead
from app.models.notification import Notification
from app.models.performance_score import PerformanceScore
from app.models.schedule_change_request import ScheduleChangeRequest
from app.models.target import Target
from app.models.task import Task
from app.models.task_checklist_item import TaskChecklistItem
from app.models.task_document import TaskDocument
from app.models.task_time_log import TaskTimeLog
from app.models.time_session import TimeSession
from app.models.user import User
from app.models.work_schedule import WorkSchedule
from app.services.audit import AuditService


def _unlink_inside(root: Path, filename: str) -> None:
    base = root.resolve()
    path = (base / filename).resolve()
    if path.parent == base and path.is_file():
        path.unlink()


def delete_employee(db: Session, employee_id: int, admin: User) -> None:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin.employee_id == employee.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    user = db.query(User).filter(User.employee_id == employee.id).first()
    if user and (user.id == admin.id or user.role == UserRole.ADMIN):
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted here")
    if employee.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted here")

    previous = {"name": employee.name, "email": employee.email, "employee_code": employee.employee_code}
    task_ids = [row[0] for row in db.query(Task.id).filter(Task.assigned_employee_id == employee.id).all()]
    lead_ids = [row[0] for row in db.query(Lead.id).filter(Lead.employee_id == employee.id).all()]

    document_filters = []
    if task_ids:
        document_filters.append(TaskDocument.task_id.in_(task_ids))
    if user:
        document_filters.append(TaskDocument.uploaded_by_user_id == user.id)
    if document_filters:
        documents = db.query(TaskDocument).filter(or_(*document_filters)).all()
        for document in documents:
            _unlink_inside(settings.upload_path / "tasks", document.stored_name)
            db.delete(document)
        db.flush()

    if task_ids:
        db.query(TaskChecklistItem).filter(TaskChecklistItem.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(TaskTimeLog).filter(TaskTimeLog.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(TaskTimeLog).filter(TaskTimeLog.employee_id == employee.id).delete(synchronize_session=False)
    db.query(Task).filter(Task.assigned_employee_id == employee.id).delete(synchronize_session=False)

    if user:
        db.query(Task).filter(Task.assigned_by_id == user.id).update({Task.assigned_by_id: None}, synchronize_session=False)
        db.query(AttendanceRecord).filter(AttendanceRecord.corrected_by == user.id).update(
            {AttendanceRecord.corrected_by: None}, synchronize_session=False
        )
        db.query(ExceptionRecord).filter(ExceptionRecord.resolved_by == user.id).update(
            {ExceptionRecord.resolved_by: None}, synchronize_session=False
        )
        db.query(ScheduleChangeRequest).filter(ScheduleChangeRequest.reviewed_by == user.id).update(
            {ScheduleChangeRequest.reviewed_by: None}, synchronize_session=False
        )
        db.query(HREvaluation).filter(
            HREvaluation.evaluator_id == user.id,
            HREvaluation.employee_id != employee.id,
        ).update({HREvaluation.evaluator_id: admin.id}, synchronize_session=False)
        db.query(Announcement).filter(Announcement.created_by_user_id == user.id).update(
            {Announcement.created_by_user_id: admin.id}, synchronize_session=False
        )
        db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
        db.query(ChatMessage).filter(ChatMessage.sender_id == user.id).delete(synchronize_session=False)
        db.query(ChatParticipant).filter(ChatParticipant.user_id == user.id).delete(synchronize_session=False)

    db.query(TimeSession).filter(TimeSession.employee_id == employee.id).delete(synchronize_session=False)
    db.query(ScheduleChangeRequest).filter(ScheduleChangeRequest.employee_id == employee.id).delete(synchronize_session=False)
    db.query(WorkSchedule).filter(WorkSchedule.employee_id == employee.id).delete(synchronize_session=False)
    db.query(AttendanceRecord).filter(AttendanceRecord.employee_id == employee.id).delete(synchronize_session=False)
    db.query(ExceptionRecord).filter(ExceptionRecord.employee_id == employee.id).delete(synchronize_session=False)
    db.query(PerformanceScore).filter(PerformanceScore.employee_id == employee.id).delete(synchronize_session=False)
    db.query(HREvaluation).filter(HREvaluation.employee_id == employee.id).delete(synchronize_session=False)
    db.query(Target).filter(Target.employee_id == employee.id).delete(synchronize_session=False)

    activity_filters = [Activity.employee_id == employee.id]
    if lead_ids:
        activity_filters.append(Activity.lead_id.in_(lead_ids))
    db.query(Activity).filter(or_(*activity_filters)).delete(synchronize_session=False)
    db.query(Lead).filter(Lead.employee_id == employee.id).delete(synchronize_session=False)
    db.query(DataSource).filter(DataSource.employee_name == employee.name).update(
        {DataSource.is_active: False}, synchronize_session=False
    )

    if employee.profile_photo_url:
        filename = employee.profile_photo_url.rsplit("/", 1)[-1]
        if PROFILE_FILE.match(filename):
            _unlink_inside(settings.upload_path / "profile", filename)

    if user:
        db.delete(user)
        db.flush()
    db.delete(employee)
    AuditService(db).log("employee_deleted", admin, "employee", employee_id, previous, None)
    db.commit()
