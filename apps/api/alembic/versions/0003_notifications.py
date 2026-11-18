"""background_jobs + notifications：worker 任务表与模拟收件箱

Revision ID: 0003
Create Date: 2026-11-17

手写迁移（docs/07）。追加在 0002 之后，保持单一头；B 的目录/值班迁移从 0004 起接。
路线图原本把 `background_jobs` 挂在 B 的迁移清单下，2026-11-17 由 A 一并落地：
通知投递与 outbox 消费都在 A 侧，先把表与租约语义定下来，B 只注册自有处理器。
`background_jobs` 的列名必须与 `app/worker/registry.py` 的 SQL 保持一致。
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("job_type", sa.String(40), nullable=False),
        sa.Column("business_key", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="PENDING"
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("business_key", name="uq_background_jobs_business_key"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')",
            name="ck_background_jobs_status",
        ),
    )
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
    op.create_index("ix_background_jobs_planned_at", "background_jobs", ["planned_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("business_key", sa.String(200), nullable=False),
        sa.Column("job_id", sa.String(40), nullable=True),
        sa.Column("template", sa.String(24), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("recipient_user_id", sa.String(40), nullable=False),
        sa.Column("recipient_email", sa.String(120), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(8), nullable=False, server_default="SENT"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"], ["background_jobs.id"], name="fk_notifications_job_id", ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "recipient_user_id", "business_key", name="uq_notifications_recipient_business_key"
        ),
        sa.CheckConstraint(
            "template IN ('NIGHT_ROSTER', 'DAILY_REPORT', 'WEEKLY_REPORT', 'RISK_ALERT')",
            name="ck_notifications_template",
        ),
        sa.CheckConstraint(
            "channel IN ('EMAIL', 'INBOX')", name="ck_notifications_channel"
        ),
        sa.CheckConstraint(
            "status IN ('SENT', 'READ')", name="ck_notifications_status"
        ),
    )
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"])
    op.create_index("ix_notifications_job_id", "notifications", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_job_id", table_name="notifications")
    op.drop_index("ix_notifications_recipient_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_background_jobs_planned_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_job_type", table_name="background_jobs")
    op.drop_table("background_jobs")
