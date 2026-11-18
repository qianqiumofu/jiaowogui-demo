"""唯一调度表：background_jobs（列语义与 app/worker/registry.py 对齐）

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("business_key", sa.String(128), nullable=False, unique=True),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')",
            name="ck_background_jobs_status",
        ),
    )
    op.create_index("ix_jobs_due", "background_jobs", ["status", "planned_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_due", table_name="background_jobs")
    op.drop_table("background_jobs")
