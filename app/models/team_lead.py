from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TeamLeadAssignment(Base):
    __tablename__ = "team_lead_assignments"
    __table_args__ = (
        UniqueConstraint("team_lead_id", "employee_id", name="uq_team_lead_pair"),
        CheckConstraint("team_lead_id != employee_id", name="ck_team_lead_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_lead_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
