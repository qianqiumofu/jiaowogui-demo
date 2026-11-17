"""reservations 与 reservation_revisions 初始建表

Revision ID: 0001
Create Date: 2026-11-17

手写迁移（docs/07：唯一约束与状态检查用手写）。这是迁移头的第一个版本，
B 的目录/关系表在其后追加，保持单一头。
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("student_id", sa.String(40), nullable=False),
        sa.Column("school_id", sa.String(40), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("planned_return_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("student_id", "service_date", name="uq_reservations_student_night"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'CANCELLED', 'FULFILLED', 'CLOSED')",
            name="ck_reservations_status",
        ),
    )
    op.create_index("ix_reservations_student_id", "reservations", ["student_id"])

    op.create_table(
        "reservation_revisions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "reservation_id",
            sa.String(40),
            sa.ForeignKey("reservations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("planned_return_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("changed_by", sa.String(40), nullable=True),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "reservation_id", "version", "source", name="uq_reservation_revisions_version"
        ),
        sa.CheckConstraint(
            "source IN ('CREATE', 'RESCHEDULE', 'CANCEL', 'RESTORE', 'CLOSE')",
            name="ck_reservation_revisions_source",
        ),
    )
    op.create_index(
        "ix_reservation_revisions_reservation_id", "reservation_revisions", ["reservation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_reservation_revisions_reservation_id", table_name="reservation_revisions")
    op.drop_table("reservation_revisions")
    op.drop_index("ix_reservations_student_id", table_name="reservations")
    op.drop_table("reservations")
