"""园区受控导出任务：export_jobs

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17

M4「受控导出」落地表（B 主责，`export:create`）。一行 = 一次导出请求：登记的永远是
统计口径 + 聚合结果，不存明细行，所以联系方式与个人身份天然不在导出范围内（R11）。
`expires_at` 由 `EXPORT_RETENTION_DAYS` 算出；保留期后读取路径清空 `csv_content` 但保留
这一行做审计。任务本体仍走 `background_jobs`（EXPORT_BUILD），本表不重复调度语义。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("export_id", sa.String(32), primary_key=True),
        sa.Column("report", sa.String(32), nullable=False),
        sa.Column(
            "requested_by",
            sa.String(32),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("file_name", sa.String(128), nullable=True),
        sa.Column("csv_content", sa.Text, nullable=True),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "report IN ('STATISTICS')",
            name="ck_export_jobs_report",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')",
            name="ck_export_jobs_status",
        ),
    )
    op.create_index("ix_export_requested_by", "export_jobs", ["requested_by", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_export_requested_by", table_name="export_jobs")
    op.drop_table("export_jobs")
