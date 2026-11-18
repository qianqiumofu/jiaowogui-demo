"""通知投递的两张表：`background_jobs` 是 worker 的任务队列，`notifications` 是模拟收件箱。

规则来源：R12（23:30 名单）、R13（日报周报）、R16（预警收件人）、基线「报告、风险和权限默认」
（渠道按账号来源分流、模拟邮件只进预览收件箱）。

`background_jobs` 的列名与 `app/worker/registry.py` 里的 SQL 一一对应，B 的任务处理器共用同一张表；
通知负载不落列，统一放 `payload`，避免和后续模块抢字段。
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JOB_STATUSES = ("PENDING", "RUNNING", "DONE", "FAILED")
TEMPLATES = ("NIGHT_ROSTER", "DAILY_REPORT", "WEEKLY_REPORT", "RISK_ALERT")
CHANNELS = ("EMAIL", "INBOX")
NOTIFICATION_STATUSES = ("SENT", "READ")

NOTIFICATION_JOB_TYPE = "NOTIFICATION_SEND"


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_background_jobs_business_key"),
        CheckConstraint(f"status IN {JOB_STATUSES!r}", name="ck_background_jobs_status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    business_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Notification(Base):
    """一条 = 一个收件人的一份正文；重复投递由 (recipient_user_id, business_key) 拦住。"""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id", "business_key", name="uq_notifications_recipient_business_key"
        ),
        CheckConstraint(f"template IN {TEMPLATES!r}", name="ck_notifications_template"),
        CheckConstraint(f"channel IN {CHANNELS!r}", name="ck_notifications_channel"),
        CheckConstraint(
            f"status IN {NOTIFICATION_STATUSES!r}", name="ck_notifications_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    business_key: Mapped[str] = mapped_column(String(200), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template: Mapped[str] = mapped_column(String(24), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    recipient_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="SENT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
