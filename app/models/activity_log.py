from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivityLog(Base):
    """Append-only work history for team oversight. Rows are never updated or deleted."""

    __tablename__ = "activity_log"
    __table_args__ = (
        UniqueConstraint("backfill_key", name="uq_activity_log_backfill"),
        Index("ix_activity_log_action_created", "action_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    target_employee_id: Mapped[int | None] = mapped_column(Integer, index=True)
    team_lead_id: Mapped[int | None] = mapped_column(Integer, index=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    backfill_key: Mapped[str | None] = mapped_column(String(80))
