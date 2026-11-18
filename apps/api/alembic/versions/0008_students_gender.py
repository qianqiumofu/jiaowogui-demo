"""学生性别维度：students.gender

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17

片区（闵行 9 个园区）复用 `organizations` 的 `CAMPUS_PARK` 层级与 `buildings.campus_org_id`，
不需要结构变更；楼栋与片区的具体行由 B 的合成 seed 写入（docs/10）。
本迁移只加性别列：园区端按「学院、片区、楼栋、年级、男女」筛选统计（R14）。

回填规则与 `app/db/seed.py` 的 `_student_row` 完全一致（奇数学号 MALE、偶数 FEMALE），
保证不重跑 seed 的库也能直接按性别筛选。

"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_STUDENT_GENDERS = ("MALE", "FEMALE")


def upgrade() -> None:
    op.add_column("students", sa.Column("gender", sa.String(8), nullable=True))
    op.execute(
        """
        UPDATE students
        SET gender = CASE
            WHEN substring(student_id from 11 for 4)::int % 2 = 1 THEN 'MALE'
            ELSE 'FEMALE'
        END
        WHERE gender IS NULL
        """
    )
    op.alter_column("students", "gender", existing_type=sa.String(8), nullable=False)
    op.create_check_constraint(
        "ck_students_gender", "students", f"gender IN {_STUDENT_GENDERS}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_students_gender", "students", type_="check")
    op.drop_column("students", "gender")
