"""人员登记：users、students

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("school_id", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("login_name", sa.String(64), nullable=False, unique=True),
    )
    op.create_table(
        "students",
        sa.Column("student_id", sa.String(32), primary_key=True),
        sa.Column("school_id", sa.String(32), nullable=False, unique=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.user_id"), nullable=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column(
            "college_org_id", sa.String(32), sa.ForeignKey("organizations.org_id"), nullable=False
        ),
        sa.Column("grade", sa.String(8), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("students")
    op.drop_table("users")
