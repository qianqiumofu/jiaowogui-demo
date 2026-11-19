"""通行二维码与正式返宿记录：pass_codes、return_records，并给 devices 补设备令牌

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17

`reservation_id` 只按 ID 引用 A 的预约，不加外键：预约表由 A 在 M2 落地，
B 的迁移不能依赖对方建表顺序（基线「跨模块只调用领域服务函数」）。
`uq_return_per_night` 实现「一学生一业务夜最多一条正式返宿」，并发与重放靠它收敛。

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b0007"
down_revision = "b0006"
branch_labels = None
depends_on = None

_PASS_STATUS = ("ISSUED", "CONSUMED", "EXPIRED", "REVOKED")
_RETURN_SOURCE = ("QR", "MANUAL")


def upgrade() -> None:
    op.create_table(
        "pass_codes",
        sa.Column("pass_id", sa.String(32), primary_key=True),
        sa.Column("reservation_id", sa.String(32), nullable=False),
        sa.Column(
            "student_id", sa.String(32), sa.ForeignKey("students.student_id"), nullable=False
        ),
        sa.Column(
            "building_id", sa.String(32), sa.ForeignKey("buildings.building_id"), nullable=False
        ),
        sa.Column("gate_id", sa.String(32), sa.ForeignKey("gates.gate_id"), nullable=True),
        sa.Column("verification_id", sa.String(32), nullable=False),
        sa.Column("reservation_version", sa.Integer, nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ISSUED"),
        sa.CheckConstraint(
            f"status IN {_PASS_STATUS}", name="ck_pass_codes_status"
        ),
    )
    op.create_index("ix_pass_codes_service_date", "pass_codes", ["service_date"])
    op.create_index("ix_pass_codes_reservation", "pass_codes", ["reservation_id"])
    op.create_index(
        "uq_one_active_pass_per_reservation",
        "pass_codes",
        ["reservation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ISSUED'"),
    )

    op.create_table(
        "return_records",
        sa.Column("return_id", sa.String(32), primary_key=True),
        sa.Column(
            "student_id", sa.String(32), sa.ForeignKey("students.student_id"), nullable=False
        ),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("pass_id", sa.String(32), sa.ForeignKey("pass_codes.pass_id"), nullable=True),
        sa.Column("gate_id", sa.String(32), sa.ForeignKey("gates.gate_id"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.CheckConstraint(f"source IN {_RETURN_SOURCE}", name="ck_return_records_source"),
        sa.UniqueConstraint("student_id", "service_date", name="uq_return_per_night"),
    )
    op.create_index("ix_return_records_service_date", "return_records", ["service_date"])

    op.add_column("devices", sa.Column("token_digest", sa.String(64), nullable=True))
    op.execute(
        "UPDATE devices SET token_digest = "
        "encode(sha256(convert_to('dev_synth:' || device_id, 'UTF8')), 'hex')"
    )
    op.alter_column("devices", "token_digest", existing_type=sa.String(64), nullable=False)


def downgrade() -> None:
    op.drop_column("devices", "token_digest")
    op.drop_index("ix_return_records_service_date", table_name="return_records")
    op.drop_table("return_records")
    op.drop_index("uq_one_active_pass_per_reservation", table_name="pass_codes")
    op.drop_index("ix_pass_codes_reservation", table_name="pass_codes")
    op.drop_index("ix_pass_codes_service_date", table_name="pass_codes")
    op.drop_table("pass_codes")
