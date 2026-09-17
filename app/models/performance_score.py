from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PerformanceScore(Base):
    __tablename__ = "performance_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), default="weekly")
    attendance_score: Mapped[float] = mapped_column(Float, default=0.0)
    task_completion_score: Mapped[float] = mapped_column(Float, default=0.0)
    deadline_score: Mapped[float] = mapped_column(Float, default=0.0)
    schedule_score: Mapped[float] = mapped_column(Float, default=0.0)
    evaluation_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    breakdown: Mapped[str | None] = mapped_column(Text)
    penalties_applied: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="performance_scores")
