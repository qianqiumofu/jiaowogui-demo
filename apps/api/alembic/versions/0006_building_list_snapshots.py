"""24:00 汇总快照：building_list_snapshots

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "building_list_snapshots",
        sa.Column("snapshot_id", sa.String(32), primary_key=True),
        sa.Column(
            "building_id", sa.String(32), sa.ForeignKey("buildings.building_id"), nullable=False
        ),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("building_id", "service_date", name="uq_snapshot_night"),
    )


def downgrade() -> None:
    op.drop_table("building_list_snapshots")
