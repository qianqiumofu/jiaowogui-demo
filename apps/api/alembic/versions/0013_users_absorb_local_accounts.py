"""users 吸收 local_staff_accounts：工号账号与统一身份同表（R18、R19）

Revision ID: 0013
Create Date: 2026-11-18

2026-11-18 整合 B 的交付时定下：人员只留 `users` 一张表，靠 `source` 区分两类账号。
`school_id` 对工号账号按登录名登记——雇佣人员没有校内编号，而 A 侧的 Person 身份一直就是
这么映射的。搬完即删 `local_staff_accounts`，不改写 0011 的建表内容。
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "b0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新的整合迁移尚未发布：先保留 A 已允许的 ID/登录名/展示名容量，再搬数据。
    op.alter_column("users", "user_id", type_=sa.String(40))
    op.alter_column("users", "school_id", type_=sa.String(64))
    op.alter_column("users", "display_name", type_=sa.String(80))
    op.add_column("users", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column(
        "users",
        sa.Column("source", sa.String(16), nullable=False, server_default="UNIFIED_SCHOOL"),
    )
    op.add_column("users", sa.Column("password", sa.String(64), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "building_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
    )
    op.add_column("users", sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_users_source", "users", "source IN ('UNIFIED_SCHOOL', 'STAFF_LOCAL')"
    )
    op.create_check_constraint("ck_users_status", "users", "status IN ('ACTIVE', 'DISABLED')")

    op.execute(
        """
        INSERT INTO users (user_id, school_id, display_name, login_name,
                           source, password, building_ids, status, disabled_at, created_at, updated_at)
        SELECT id, login_name, display_name, login_name,
               'STAFF_LOCAL', password, building_ids, status, disabled_at, created_at, updated_at
        FROM local_staff_accounts
        """
    )

    op.drop_index("ix_local_staff_accounts_login_name", table_name="local_staff_accounts")
    op.drop_table("local_staff_accounts")


def downgrade() -> None:
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
    op.execute(
        """
        INSERT INTO local_staff_accounts (id, login_name, display_name, password,
                                          building_ids, status, disabled_at, created_at, updated_at)
        SELECT user_id, login_name, display_name, password,
               building_ids, status, disabled_at, created_at, updated_at
        FROM users
        WHERE source = 'STAFF_LOCAL'
        """
    )
    op.execute("DELETE FROM users WHERE source = 'STAFF_LOCAL'")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_constraint("ck_users_source", "users", type_="check")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "status")
    op.drop_column("users", "building_ids")
    op.drop_column("users", "password")
    op.drop_column("users", "source")
