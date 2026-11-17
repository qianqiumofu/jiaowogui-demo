"""预约聚合：一晚一条（student_id, service_date 唯一），修订历史只追加。

规则来源：R05 唯一、R06 自动通过、R07 无限改期保留历史、基线「取消后恢复同一 ID」。
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUSES = ("ACTIVE", "CANCELLED", "FULFILLED", "CLOSED")
REVISION_SOURCES = ("CREATE", "RESCHEDULE", "CANCEL", "RESTORE", "CLOSE")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("student_id", "service_date", name="uq_reservations_student_night"),
        CheckConstraint(
            f"status IN {STATUSES!r}",
            name="ck_reservations_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    school_id: Mapped[str] = mapped_column(String(40), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    planned_return_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReservationRevision(Base):
    __tablename__ = "reservation_revisions"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id", "version", "source", name="uq_reservation_revisions_version"
        ),
        CheckConstraint(
            f"source IN {REVISION_SOURCES!r}",
            name="ck_reservation_revisions_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    planned_return_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    changed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
