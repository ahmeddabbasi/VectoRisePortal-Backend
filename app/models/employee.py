from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    job_title: Mapped[str | None] = mapped_column(String(100))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    role: Mapped[str] = mapped_column(String(50), default="employee")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    joining_date: Mapped[date | None] = mapped_column(Date)
    profile_photo_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    department: Mapped["Department | None"] = relationship(back_populates="employees")
    user: Mapped["User | None"] = relationship(back_populates="employee", uselist=False)
    leads: Mapped[list["Lead"]] = relationship(back_populates="employee")
    activities: Mapped[list["Activity"]] = relationship(back_populates="employee")
    targets: Mapped[list["Target"]] = relationship(back_populates="employee")
    work_schedules: Mapped[list["WorkSchedule"]] = relationship(back_populates="employee")
    schedule_change_requests: Mapped[list["ScheduleChangeRequest"]] = relationship(back_populates="employee")
    attendance_records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="employee")
    tasks: Mapped[list["Task"]] = relationship(back_populates="assignee", foreign_keys="Task.assigned_employee_id")
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(back_populates="employee")
    performance_scores: Mapped[list["PerformanceScore"]] = relationship(back_populates="employee")
    hr_evaluations: Mapped[list["HREvaluation"]] = relationship(back_populates="employee")
