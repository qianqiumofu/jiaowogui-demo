"""楼栋固定值班名册：building_duty_roster

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-20

需求方 2026-11-18 定的口径：**每栋楼的夜间值班是固定的**，园区端的值班授权因此只登记
「某夜谁来代班」，不再逐夜授主值。固定关系属于名录事实，代班才是按夜的临时追加。

与基线原口径的调和（基线 v1.7「不引入一人固定一栋、一栋只有一位主值的限制」）：
本表把「逐夜主值行」升格成「长期生效的固定班」，但**不限制一栋只能有一位**——千人场景每栋
并排白班（06:00—18:00）与夜班（18:00—次日 06:00）两位，唯一约束落在 `(building_id, staff_user_id)`，
一人多栋同样允许。也就是说：否决的是「一栋一位」这条限制，保留的是「名册是值守范围的唯一来源」。

窗口存 `time` 而不是时间戳：固定班每晚重复同一个时刻段，跨零点由读取侧按业务夜回绕判定
（`shift_start > shift_end` 走回绕分支），所以这里没有 `service_date`。`valid_from/valid_to`
只表达「这套固定班从哪一夜起算、到哪一夜失效」，不是逐夜授权。

回填有两个来源，顺序不能反：先按 `duty_assignments` 里已有的主值行现算班次窗口（那是真实班次），
再补 `users.building_ids` 里登记过楼栋、却没有任何主值行的工号账号（缺省按夜班窗口），
最后删掉历史的逐夜主值行——该语义已由本表承担，留着会让同一夜的负责人被算两遍。
代班行（`is_substitute`）原样保留。downgrade 只还原表结构，不重建被删的主值行。
"""

import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

NIGHT_START_HOUR = 6
DEFAULT_SHIFT_START = "18:00"
DEFAULT_SHIFT_END = "06:00"

_CREATE_ROSTER = """
CREATE TABLE building_duty_roster (
    roster_id VARCHAR(40) PRIMARY KEY,
    building_id VARCHAR(32) NOT NULL REFERENCES buildings (building_id),
    staff_user_id VARCHAR(40) NOT NULL REFERENCES users (user_id),
    shift_start TIME NOT NULL,
    shift_end TIME NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_duty_roster_slot UNIQUE (building_id, staff_user_id),
    CONSTRAINT ck_duty_roster_window CHECK (shift_start <> shift_end),
    CONSTRAINT ck_duty_roster_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from)
)
"""

_INSERT_ROSTER = """
INSERT INTO building_duty_roster
    (roster_id, building_id, staff_user_id, shift_start, shift_end, valid_from, valid_to)
VALUES
    (:roster_id, :building_id, :staff_user_id, :shift_start, :shift_end, :valid_from, NULL)
ON CONFLICT (building_id, staff_user_id) DO NOTHING
"""


def _business_timezone() -> ZoneInfo:
    from app.core.config import get_settings

    return ZoneInfo(get_settings().business_timezone)


def _clock_of(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _roster_id(building_id: str, staff_user_id: str) -> str:
    """主键只有 40 位，楼栋 32 + 工号 40 拼起来必截断；截断段留楼栋，其余取摘要。"""
    digest = hashlib.sha1(f"{building_id}|{staff_user_id}".encode()).hexdigest()[:12]
    return f"roster_{building_id[:16]}_{digest}"


def _rows_from_primary_duty(conn, tz: ZoneInfo) -> list[dict]:
    """已有主值行 → 固定班：同一人同一栋只留一条，班次取那一夜重复的时刻段。"""
    grouped: dict[tuple[str, str], dict] = {}
    rows = conn.execute(
        sa.text(
            """
            SELECT building_id, staff_user_id, service_date, shift_start, shift_end
            FROM duty_assignments
            WHERE NOT is_substitute
            ORDER BY building_id, staff_user_id, service_date
            """
        )
    ).mappings()
    for row in rows:
        key = (str(row["building_id"]), str(row["staff_user_id"]))
        start = row["shift_start"].astimezone(tz)
        end = row["shift_end"].astimezone(tz)
        night = row["service_date"]
        current = grouped.get(key)
        if current is None:
            grouped[key] = {
                "building_id": key[0],
                "staff_user_id": key[1],
                "shift_start": _clock_of(start),
                "shift_end": _clock_of(end),
                "valid_from": night,
            }
        elif night < current["valid_from"]:
            current["valid_from"] = night
    return list(grouped.values())


def _rows_from_account_scope(conn, tz: ZoneInfo, taken: set[tuple[str, str]]) -> list[dict]:
    """工号账号登记过楼栋却没有主值行：按夜班窗口补一条，否则迁移后她会失去全部范围。

    只补目录里真存在的楼栋——`building_ids` 是账号自由填的 json，历史库里留着早已下架的楼号，
    照抄会撞上本表对 `buildings` 的外键（迁移在真实旧库上必须一次过）。
    """
    fallback_from = (datetime.now(tz) - timedelta(days=365)).date()
    extra: dict[tuple[str, str], dict] = {}
    accounts = conn.execute(
        sa.text("SELECT user_id, building_ids::text AS scope FROM users WHERE source = 'STAFF_LOCAL'")
    ).mappings()

    for account in accounts:
        raw = account["scope"]
        if not raw:
            continue
        for building_id in json.loads(raw):
            key = (str(building_id), str(account["user_id"]))
            if key in taken or key in extra:
                continue
            if conn.execute(
                sa.text("SELECT 1 FROM buildings WHERE building_id = :building_id"),
                {"building_id": key[0]},
            ).scalar() is None:
                continue
            extra[key] = {
                "building_id": key[0],
                "staff_user_id": key[1],
                "shift_start": DEFAULT_SHIFT_START,
                "shift_end": DEFAULT_SHIFT_END,
                "valid_from": fallback_from,
            }
    return list(extra.values())


def upgrade() -> None:
    bind = op.get_bind()
    tz = _business_timezone()

    op.execute(_CREATE_ROSTER)
    op.create_index("ix_duty_roster_staff", "building_duty_roster", ["staff_user_id"])
    op.create_index("ix_duty_roster_building", "building_duty_roster", ["building_id"])

    rows = _rows_from_primary_duty(bind, tz)
    taken = {(row["building_id"], row["staff_user_id"]) for row in rows}
    rows += _rows_from_account_scope(bind, tz, taken)
    for row in rows:
        roster_id = _roster_id(row["building_id"], row["staff_user_id"])
        bind.execute(
            sa.text(_INSERT_ROSTER),
            {
                "roster_id": roster_id,
                "building_id": row["building_id"],
                "staff_user_id": row["staff_user_id"],
                "shift_start": row["shift_start"],
                "shift_end": row["shift_end"],
                "valid_from": row["valid_from"],
            },
        )

    op.execute("DELETE FROM duty_assignments WHERE NOT is_substitute")


def downgrade() -> None:
    op.drop_index("ix_duty_roster_building", table_name="building_duty_roster")
    op.drop_index("ix_duty_roster_staff", table_name="building_duty_roster")
    op.drop_table("building_duty_roster")
