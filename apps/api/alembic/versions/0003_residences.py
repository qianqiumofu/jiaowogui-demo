"""住宿关系：residences

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "residences",
        sa.Column("residence_id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id", sa.String(32), sa.ForeignKey("students.student_id"), nullable=False
        ),
        sa.Column(
            "building_id", sa.String(32), sa.ForeignKey("buildings.building_id"), nullable=False
        ),
        sa.Column("room_no", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.UniqueConstraint("student_id", "valid_from", name="uq_residence_per_night_start"),
    )
    op.create_index("ix_residences_building_valid", "residences", ["building_id", "valid_from"])
    op.create_index("ix_residences_student_valid", "residences", ["student_id", "valid_from"])


def downgrade() -> None:
    op.drop_index("ix_residences_student_valid", table_name="residences")
    op.drop_index("ix_residences_building_valid", table_name="residences")
    op.drop_table("residences")
