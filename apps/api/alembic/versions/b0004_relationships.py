"""负责与值班代班关系：counselor_assignments、duty_assignments

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa

revision = "b0004"
down_revision = "b0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counselor_assignments",
        sa.Column("assignment_id", sa.String(32), primary_key=True),
        sa.Column(
            "counselor_user_id", sa.String(32), sa.ForeignKey("users.user_id"), nullable=False
        ),
        sa.Column(
            "student_id", sa.String(32), sa.ForeignKey("students.student_id"), nullable=False
        ),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.UniqueConstraint(
            "counselor_user_id", "student_id", "valid_from", name="uq_counselor_assignment"
        ),
    )
    op.create_table(
        "duty_assignments",
        sa.Column("duty_id", sa.String(32), primary_key=True),
        sa.Column(
            "staff_user_id", sa.String(32), sa.ForeignKey("users.user_id"), nullable=False
        ),
        sa.Column(
            "building_id", sa.String(32), sa.ForeignKey("buildings.building_id"), nullable=False
        ),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_substitute", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint(
            "staff_user_id", "building_id", "service_date", "shift_start", name="uq_duty_slot"
        ),
    )
    op.create_index("ix_duty_building_date", "duty_assignments", ["building_id", "service_date"])
    op.create_index("ix_duty_staff_date", "duty_assignments", ["staff_user_id", "service_date"])


def downgrade() -> None:
    op.drop_index("ix_duty_staff_date", table_name="duty_assignments")
    op.drop_index("ix_duty_building_date", table_name="duty_assignments")
    op.drop_table("duty_assignments")
    op.drop_table("counselor_assignments")
