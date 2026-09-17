from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(100), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    current_stage: Mapped[str | None] = mapped_column(String(80), index=True)
    reply_status: Mapped[str | None] = mapped_column(String(80))
    meeting_status: Mapped[str | None] = mapped_column(String(80))
    opportunity_status: Mapped[str | None] = mapped_column(String(80))
    source_sheet: Mapped[str] = mapped_column(String(120))
    source_sheet_id: Mapped[str] = mapped_column(String(100))
    source_row: Mapped[int] = mapped_column(Integer)
    source_gid: Mapped[int] = mapped_column(Integer)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_group: Mapped[str | None] = mapped_column(String(64), index=True)
    last_activity_date: Mapped[date | None] = mapped_column(Date)
    next_follow_up_date: Mapped[date | None] = mapped_column(Date)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="leads")
    activities: Mapped[list["Activity"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
