"""local_staff_accounts：园区为雇佣人员注册的宿管工号账号

Revision ID: 0002
Create Date: 2026-11-17

手写迁移（docs/07）。追加在 0001 之后，保持单一头；B 的目录/任务表从 0003 起接。
表名刻意不叫 `users`：学校统一身份不入库，本表只存园区自建的工作账号，
B 的 `users`/目录落地后若要合并，用新迁移搬数据，不重命名本表。
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_staff_accounts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("login_name", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("password", sa.String(64), nullable=False),
        sa.Column("building_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("login_name", name="uq_local_staff_accounts_login_name"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')", name="ck_local_staff_accounts_status"
        ),
    )
    op.create_index(
        "ix_local_staff_accounts_login_name", "local_staff_accounts", ["login_name"]
    )


def downgrade() -> None:
    op.drop_index("ix_local_staff_accounts_login_name", table_name="local_staff_accounts")
    op.drop_table("local_staff_accounts")
