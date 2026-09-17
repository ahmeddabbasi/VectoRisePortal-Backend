from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        Index("ix_attendance_emp_date", "employee_id", "work_date", unique=True),
        Index("ix_attendance_work_date", "work_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), default="incomplete")
    check_in_status: Mapped[str | None] = mapped_column(String(30))
    check_out_status: Mapped[str | None] = mapped_column(String(30))
    total_minutes: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    is_corrected: Mapped[bool] = mapped_column(default=False)
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    correction_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="attendance_records")
    time_sessions: Mapped[list["TimeSession"]] = relationship(back_populates="attendance_record")
