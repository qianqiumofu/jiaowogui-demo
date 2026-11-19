"""目录基础：organizations、buildings、gates、devices

Revision ID: 0001
Revises:
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa

revision = "b0001"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("org_id", sa.String(32), primary_key=True),
        sa.Column("org_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "parent_org_id",
            sa.String(32),
            sa.ForeignKey("organizations.org_id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "org_type IN ('COLLEGE', 'CAMPUS_PARK')", name="ck_organizations_type"
        ),
    )
    op.create_table(
        "buildings",
        sa.Column("building_id", sa.String(32), primary_key=True),
        sa.Column(
            "campus_org_id", sa.String(32), sa.ForeignKey("organizations.org_id"), nullable=False
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
    )
    op.create_table(
        "gates",
        sa.Column("gate_id", sa.String(32), primary_key=True),
        sa.Column(
            "building_id", sa.String(32), sa.ForeignKey("buildings.building_id"), nullable=False
        ),
        sa.Column("name", sa.String(64), nullable=False),
    )
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(32), primary_key=True),
        sa.Column("gate_id", sa.String(32), sa.ForeignKey("gates.gate_id"), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("devices")
    op.drop_table("gates")
    op.drop_table("buildings")
    op.drop_table("organizations")
