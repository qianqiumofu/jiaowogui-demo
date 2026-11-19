"""结构一致性修复：子列加宽到 40 并补 users.college_org_id 外键。

0013/0015 把 users.user_id 加宽到 VARCHAR(40)，但引用它的子列仍停在 VARCHAR(32)；
一旦使用 33—40 位的 user_id，写入 students/counselor_assignments/duty_assignments/export_jobs
会因 value too long 失败。0016 追加 users.college_org_id 时只加列、漏建 ORM 声明的外键。
本迁移只追加，不改写已应用的旧迁移。
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("students", "user_id", existing_type=sa.String(32), type_=sa.String(40), existing_nullable=True)
    op.alter_column("counselor_assignments", "counselor_user_id", existing_type=sa.String(32), type_=sa.String(40), existing_nullable=False)
    op.alter_column("duty_assignments", "staff_user_id", existing_type=sa.String(32), type_=sa.String(40), existing_nullable=False)
    op.alter_column("export_jobs", "requested_by", existing_type=sa.String(32), type_=sa.String(40), existing_nullable=False)
    op.create_foreign_key("users_college_org_id_fkey", "users", "organizations", ["college_org_id"], ["org_id"])


def downgrade():
    op.drop_constraint("users_college_org_id_fkey", "users", type_="foreignkey")
    op.alter_column("export_jobs", "requested_by", existing_type=sa.String(40), type_=sa.String(32), existing_nullable=False)
    op.alter_column("duty_assignments", "staff_user_id", existing_type=sa.String(40), type_=sa.String(32), existing_nullable=False)
    op.alter_column("counselor_assignments", "counselor_user_id", existing_type=sa.String(40), type_=sa.String(32), existing_nullable=False)
    op.alter_column("students", "user_id", existing_type=sa.String(40), type_=sa.String(32), existing_nullable=True)
