"""园区为雇佣人员注册的本地工号账号（R19）。

不是校内统一身份：`login_name` 与学号/工号无关，`password` 为 Demo 明文合成口令，
禁止写入真实凭据。楼栋范围由园区在创建时授予，代班（B 的 duty）在此之上叠加。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUSES = ("ACTIVE", "DISABLED")


class LocalStaffAccount(Base):
    __tablename__ = "local_staff_accounts"
    __table_args__ = (
        UniqueConstraint("login_name", name="uq_local_staff_accounts_login_name"),
        CheckConstraint(f"status IN {STATUSES!r}", name="ck_local_staff_accounts_status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    login_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password: Mapped[str] = mapped_column(String(64), nullable=False)
    building_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
