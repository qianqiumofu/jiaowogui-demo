"""值班领域服务（B 主责）：每栋楼的夜间值班是固定的，园区端的授权只登记代班。

两张表各管一件事（docs/08、R11）：
- `building_duty_roster`：固定值守，窗口是每晚重复的时刻段（18:00—次日 06:00），属于名录事实。
  同一人同一栋只一条（`(building_id, staff_user_id)` 唯一），一栋可以并排白班与夜班两位。
- `duty_assignments`：只剩「某一夜某人多管一栋」的代班，按绝对时间区间生效，撤销即回收。

因此园区端不再有「逐夜授主值」这种写法：主值靠换人（一次性、长期生效），代班靠登记（按夜）。
范围出口在 `directory.get_duty_buildings`，它是三条的并集：名册固定班 ∪ 当夜代班 ∪ A 的工号账号
`building_ids`。第三条是基线已交付、测试锚死的园区授权口（建号即绑楼，还兼着通知文案里的「她管的那几栋」），
本模块不抢它的语义。为了让名册页的「卸任即收回」真的成立，卸任会顺带调 A 的
`staff_accounts.remove_building_binding` 在同一事务中解掉那一条账号绑定；反方向不成立——只绑了账号的人不会自动进名册，
所以园区端名册页看不到她。两条口子收敛成一条需要 A 侧确认，见《给A-值班授权改由园区端签发-需评审.md》。
`fixed_watch_buildings` 仅查询名册事实；风险仍沿用业务基线的统一范围，不改收件与处置角色。
新写入都会把该楼栋那一夜的 24:00 汇总排进 `background_jobs`，园区端才等得到那份晚归单。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import NIGHT_GATE_END_MINUTE, service_date_of, summary_moment
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import ApiError
from app.modules.identity.schemas import SessionContext

NIGHT_START_HOUR = NIGHT_GATE_END_MINUTE // 60  # 业务日 D = [D 06:00, D+1 06:00)

_SELECT_ROSTER_SQL = text("""
    SELECT r.* FROM building_duty_roster r
    WHERE (CAST(:staff_user_id AS VARCHAR) IS NULL OR r.staff_user_id = :staff_user_id)
      AND (CAST(:building_id AS VARCHAR) IS NULL OR r.building_id = :building_id)
    ORDER BY r.building_id, r.staff_user_id
""")
_LOAD_ROSTER_SQL = text("""
    SELECT r.* FROM building_duty_roster r
    WHERE r.building_id = :building_id
      AND (CAST(:staff_user_id AS VARCHAR) IS NULL OR r.staff_user_id = :staff_user_id)
    ORDER BY r.staff_user_id
""")

_UPSERT_ROSTER_SQL = text(
    """
    INSERT INTO building_duty_roster (roster_id, building_id, staff_user_id,
                                      shift_start, shift_end, valid_from, valid_to)
    VALUES (:roster_id, :building_id, :staff_user_id,
            :shift_start, :shift_end, :valid_from, :valid_to)
    ON CONFLICT (building_id, staff_user_id) DO UPDATE
    SET staff_user_id = EXCLUDED.staff_user_id,
        shift_start = EXCLUDED.shift_start,
        shift_end = EXCLUDED.shift_end,
        valid_from = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to,
        updated_at = NOW()
    RETURNING roster_id
    """
)

_DELETE_ROSTER_BY_BUILDING_SQL = text(
    """
    DELETE FROM building_duty_roster
    WHERE building_id = :building_id
      AND (CAST(:staff_user_id AS VARCHAR) IS NULL OR staff_user_id = CAST(:staff_user_id AS VARCHAR))
    RETURNING roster_id
    """
)

_SELECT_DUTY_SQL = text("""
    SELECT d.* FROM duty_assignments d
    WHERE (CAST(:staff_user_id AS VARCHAR) IS NULL OR d.staff_user_id = :staff_user_id)
      AND (CAST(:building_id AS VARCHAR) IS NULL OR d.building_id = :building_id)
      AND (CAST(:service_date AS DATE) IS NULL OR d.service_date = :service_date)
    ORDER BY d.service_date, d.building_id, d.shift_start, d.staff_user_id
""")

_INSERT_DUTY_SQL = text(
    """
    INSERT INTO duty_assignments (duty_id, staff_user_id, building_id, service_date,
                                  shift_start, shift_end, is_substitute)
    VALUES (:duty_id, :staff_user_id, :building_id, :service_date,
            :shift_start, :shift_end, true)
    ON CONFLICT ON CONSTRAINT uq_duty_slot DO NOTHING
    RETURNING duty_id
    """
)

_LOAD_DUTY_SQL = text("SELECT * FROM duty_assignments WHERE duty_id = :duty_id")
_DELETE_DUTY_SQL = text("DELETE FROM duty_assignments WHERE duty_id = :duty_id")

_FIXED_BUILDING_ON_NIGHT_SQL = text(
    """
    SELECT building_id
    FROM building_duty_roster
    WHERE staff_user_id = :staff_user_id
      AND valid_from <= :service_date
      AND (valid_to IS NULL OR valid_to > :service_date)
    ORDER BY building_id
    """
)

_FIXED_ON_NIGHT_SQL = text(
    """
    SELECT r.building_id, r.staff_user_id, r.shift_start, r.shift_end
    FROM building_duty_roster r
    WHERE r.valid_from <= :service_date
      AND (r.valid_to IS NULL OR r.valid_to > :service_date)
    ORDER BY r.building_id
    """
)

_SUBSTITUTE_ON_NIGHT_SQL = text(
    """
    SELECT d.building_id, d.staff_user_id, d.is_substitute,
           d.shift_start, d.shift_end
    FROM duty_assignments d
    WHERE d.service_date = :service_date
    ORDER BY d.building_id, d.shift_start, d.staff_user_id
    """
)

# 范围判定的四条：固定班看名册的 valid_from/valid_to 是否覆盖那一夜，代班看绝对班次区间。
_FIXED_STAFF_ON_BUILDING_SQL = text(
    """
    SELECT staff_user_id
    FROM building_duty_roster
    WHERE building_id = :building_id
      AND valid_from <= :service_date
      AND (valid_to IS NULL OR valid_to > :service_date)
    """
)

_SUBSTITUTE_BUILDINGS_AT_SQL = text(
    """
    SELECT building_id
    FROM duty_assignments
    WHERE staff_user_id = :staff_user_id AND shift_start <= :at AND shift_end > :at
    """
)

_SUBSTITUTE_STAFF_AT_SQL = text(
    """
    SELECT staff_user_id
    FROM duty_assignments
    WHERE building_id = :building_id AND shift_start <= :at AND shift_end > :at
    """
)

def _business_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def append_audit(conn, actor_user_id: str, action: str, target: str, payload: dict, at: datetime) -> None:
    from app.core.audit import append
    with Session(bind=conn, join_transaction_mode="rollback_only") as db:
        append(db, actor_user_id, action, target, payload, at)
        db.flush()


def _label_rows(conn, rows) -> list[dict]:
    from app.modules.directory.service import duty_labels
    rows = [dict(row) for row in rows]
    people, buildings = duty_labels(conn,
        list({row["staff_user_id"] for row in rows}), list({row["building_id"] for row in rows}))
    for row in rows:
        row["staff_name"] = row["display_name"] = people[row["staff_user_id"]]
        row.update(buildings[row["building_id"]])
    return rows


def _business_time_of(moment: datetime) -> time:
    """业务时区的墙上时刻：固定班窗口（18:00—次日 06:00）按它判定，跨零点走回绕。

    `app.core.clock` 没有这个出口，班次窗口是本模块自己的口径，不往公共时钟里塞。
    """
    if moment.tzinfo is None:
        raise ValueError("business_time_of 需要带时区时间")
    return moment.astimezone(_business_tz()).time()


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(_business_tz()).isoformat() if moment else None


def _night_of(moment: datetime) -> date:
    return service_date_of(moment)


def _clock_of(moment: time) -> str:
    return moment.strftime("%H:%M")


def _night_bounds(night: date) -> tuple[datetime, datetime]:
    tz = _business_tz()
    start = datetime.combine(night, time(NIGHT_START_HOUR, 0), tzinfo=tz)
    end = datetime.combine(night + timedelta(days=1), time(NIGHT_START_HOUR, 0), tzinfo=tz)
    return start, end


def _fixed_moment(night: date, moment_of_day: time, *, end: bool = False) -> datetime:
    """把每晚重复的时刻段落回那一夜：06:00 前的时刻属于业务夜的次日凌晨。

    06:00 本身是分界点，只能是「起」不能是「止」——18:00—次日 06:00 的收工时刻落在第二天，
    所以结束时刻用 `<=`，开始时刻用 `<`，否则快照里会出现结束早于开始的那一夜。
    """
    tz = _business_tz()
    bound = time(NIGHT_START_HOUR, 0)
    past_dawn = moment_of_day <= bound if end else moment_of_day < bound
    day = night + timedelta(days=1) if past_dawn else night
    return datetime.combine(day, moment_of_day, tzinfo=tz)


def _fixed_window(night: date, start_clock: time, end_clock: time) -> tuple[datetime, datetime]:
    start = _fixed_moment(night, start_clock)
    end = datetime.combine(start.date(), end_clock, tzinfo=_business_tz())
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _covers_night(row: Mapping[str, object], night: date) -> bool:
    valid_from = row["valid_from"]
    valid_to = row["valid_to"]
    assert isinstance(valid_from, date)
    return valid_from <= night and (valid_to is None or valid_to > night)


def _in_window(moment_of_day: time, start: time, end: time) -> bool:
    if start < end:
        return start <= moment_of_day < end
    return moment_of_day >= start or moment_of_day < end


def _shift_state(shift_start: datetime, shift_end: datetime, at: datetime) -> str:
    if at < shift_start:
        return "SCHEDULED"
    if at < shift_end:
        return "ACTIVE"
    return "ENDED"


def _as_roster_item(row: Mapping[str, object], at: datetime) -> dict:
    assert isinstance(row["shift_start"], time) and isinstance(row["shift_end"], time)
    night = _night_of(at)
    covers = _covers_night(row, night)
    return {
        "roster_id": str(row["roster_id"]),
        "building_id": str(row["building_id"]),
        "building_name": str(row["building_name"]),
        "park_org_id": str(row["park_org_id"]),
        "park_name": str(row["park_name"]),
        "staff_user_id": str(row["staff_user_id"]),
        "staff_name": str(row["staff_name"]),
        "shift_start": _clock_of(row["shift_start"]),
        "shift_end": _clock_of(row["shift_end"]),
        "valid_from": str(row["valid_from"]),
        "valid_to": str(row["valid_to"]) if row["valid_to"] else None,
        "covers_tonight": covers,
        "on_duty_now": covers and _in_window(_business_time_of(at), row["shift_start"], row["shift_end"]),
    }


def _as_duty_item(row: Mapping[str, object], at: datetime) -> dict:
    assert isinstance(row["shift_start"], datetime) and isinstance(row["shift_end"], datetime)
    return {
        "duty_id": str(row["duty_id"]),
        "staff_user_id": str(row["staff_user_id"]),
        "staff_name": str(row["staff_name"]),
        "building_id": str(row["building_id"]),
        "building_name": str(row["building_name"]),
        "park_org_id": str(row["park_org_id"]),
        "park_name": str(row["park_name"]),
        "service_date": str(row["service_date"]),
        "shift_start": _iso(row["shift_start"]),
        "shift_end": _iso(row["shift_end"]),
        "is_substitute": bool(row["is_substitute"]),
        "shift_state": _shift_state(row["shift_start"], row["shift_end"], at),
    }


def _require_text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(
            422, "VALIDATION_FAILED", f"授权缺少字段 {name}。", {"missing": name}
        )
    return value.strip()


def _require_date(payload: Mapping[str, object], name: str) -> date:
    value = payload.get(name)
    if not isinstance(value, str):
        raise ApiError(
            422, "VALIDATION_FAILED", f"字段 {name} 必须是 YYYY-MM-DD。", {"field": name}
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(
            422, "VALIDATION_FAILED", f"字段 {name} 不是合法日期。", {"field": name}
        ) from exc


def _parse_moment(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ApiError(
            422, "VALIDATION_FAILED", f"字段 {name} 必须是带时区的 ISO 时间。", {"field": name}
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(
            422, "VALIDATION_FAILED", f"字段 {name} 不是合法 ISO 时间。", {"field": name}
        ) from exc
    if parsed.tzinfo is None:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            f"字段 {name} 必须带时区，客户端不得省略。",
            {"field": name},
        )
    return parsed


def _parse_clock(payload: Mapping[str, object], name: str, default: time) -> time:
    """固定班次的窗口是「每晚几点」，用 HH:MM，不是绝对时间。"""
    value = payload.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ApiError(
            422, "VALIDATION_FAILED", f"字段 {name} 必须是 HH:MM 形式的时刻。", {"field": name}
        )
    try:
        cleaned = value.strip()
        if len(cleaned) != 5 or cleaned[2] != ":":
            raise ValueError("expected HH:MM")
        return time.fromisoformat(cleaned)
    except ValueError as exc:
        raise ApiError(
            422, "VALIDATION_FAILED", f"字段 {name} 不是合法的 HH:MM 时刻。", {"field": name}
        ) from exc


def _window(payload: Mapping[str, object], night: date) -> tuple[datetime, datetime]:
    """代班窗口缺省覆盖整个业务夜；显式给出时必须落在那一夜内。

    06:00 是业务夜的分界（R04、R12），跨夜的班次会让名单翻页与范围判定打架，直接拒绝。
    """
    start_bound, end_bound = _night_bounds(night)
    start = _parse_moment(payload["shift_start"], "shift_start") if payload.get("shift_start") else start_bound
    end = _parse_moment(payload["shift_end"], "shift_end") if payload.get("shift_end") else end_bound
    if start >= end:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "班次开始时间必须早于结束时间。",
            {"shift_start": _iso(start), "shift_end": _iso(end)},
        )
    if start < start_bound or end > end_bound:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "班次窗口必须完整落在所授权的业务夜内。",
            {
                "service_date": night.isoformat(),
                "night_start": _iso(start_bound),
                "night_end": _iso(end_bound),
                "shift_start": _iso(start),
                "shift_end": _iso(end),
            },
        )
    return start, end


def _validate_subjects(conn, staff_user_id: str, building_id: str) -> None:
    from app.modules.directory.service import validate_duty_subjects
    validate_duty_subjects(conn, staff_user_id, building_id)


# ------------------------------------------------------------------ 固定负责人
# 一人一栋组合唯一；一栋多人、一人多栋均允许。


def set_roster(payload: Mapping[str, object], at: datetime, *, actor_user_id: str) -> dict:
    """园区端登记/更换某栋楼的固定负责人：同一人同一栋只一条。

    一栋可以并排登记白班与夜班两位固定负责人，所以写入只动这一栋这一人的那一行，
    不清他在别栋的固定班；按夜的代班另在 `duty_assignments`，互不影响。
    缺省窗口就是「18:00—次日 06:00」，缺省生效日就是今晚所在的那个业务夜，换人立刻生效。
    """
    building_id = _require_text(payload, "building_id")
    staff_user_id = _require_text(payload, "staff_user_id")
    night = _night_of(at)
    valid_from = _require_date(payload, "valid_from") if payload.get("valid_from") else night
    valid_to = _require_date(payload, "valid_to") if payload.get("valid_to") else None
    settings = get_settings()
    start = _parse_clock(payload, "shift_start", time.fromisoformat(settings.duty_fixed_shift_start))
    end = _parse_clock(payload, "shift_end", time.fromisoformat(settings.duty_fixed_shift_end))
    if start == end:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "固定值班窗口的开始与结束时刻不能相同。",
            {"shift_start": _clock_of(start), "shift_end": _clock_of(end)},
        )
    if valid_to is not None and valid_to <= valid_from:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "固定值班的失效日期必须晚于生效日期。",
            {"valid_from": valid_from.isoformat(), "valid_to": valid_to.isoformat()},
        )

    with get_engine().begin() as conn:
        _validate_subjects(conn, staff_user_id, building_id)
        roster_id = conn.execute(
            _UPSERT_ROSTER_SQL,
            {
                "roster_id": f"roster_{uuid.uuid4().hex[:20]}",
                "building_id": building_id,
                "staff_user_id": staff_user_id,
                "shift_start": start,
                "shift_end": end,
                "valid_from": valid_from,
                "valid_to": valid_to,
            },
        ).scalar()
        _ensure_snapshot_job(conn, building_id, night)
        append_audit(
            conn,
            actor_user_id,
            "DUTY_ROSTER_SET",
            building_id,
            {"staff_user_id": staff_user_id, "shift_start": _clock_of(start), "shift_end": _clock_of(end)},
            at,
        )
    record = load_roster(building_id, at, staff_user_id=staff_user_id)
    assert record is not None and roster_id is not None
    return record


def revoke_roster(
    payload: Mapping[str, object], at: datetime, *, actor_user_id: str
) -> dict:
    """园区端卸任某栋楼某位固定负责人：删行的瞬间，那位阿姨的楼栋范围就不再包含它。

    一栋可能并排白班与夜班两位，所以卸任必须指到人，不做「整栋清空」。
    那一夜已登记的 24:00 汇总任务不回滚——汇总跟着业务夜走，负责人名字在汇总时刻冻结。
    """
    building_id = _require_text(payload, "building_id")
    staff_user_id = _require_text(payload, "staff_user_id")
    before = load_roster(building_id, at, staff_user_id=staff_user_id)
    if before is None:
        raise ApiError(
            404,
            "DUTY_ROSTER_NOT_FOUND",
            "该楼栋没有这位固定负责人，无需卸任。",
            {"building_id": building_id, "staff_user_id": staff_user_id},
        )
    with get_engine().begin() as conn:
        removed = conn.execute(
            _DELETE_ROSTER_BY_BUILDING_SQL,
            {"building_id": building_id, "staff_user_id": staff_user_id},
        ).scalar_one_or_none()
        if removed is None:
            raise ApiError(404, "DUTY_ROSTER_NOT_FOUND", "该名册已被撤销。", {})
        append_audit(
            conn,
            actor_user_id,
            "DUTY_ROSTER_REVOKED",
            building_id,
            {"staff_user_id": staff_user_id},
            at,
        )
        _drop_account_binding(conn, staff_user_id, building_id)
    return before


def _drop_account_binding(conn, staff_user_id: str, building_id: str) -> None:
    """卸任顺带解掉工号账号上那一条楼栋绑定，否则名册删了人、阿姨照样进得来名单。

    走身份领域服务并加入调用方事务；失败时名册、审计和账号绑定一起回滚。
    """
    from app.modules.identity import staff_accounts

    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        staff_accounts.remove_building_binding(session, staff_user_id, building_id)
        session.flush()


def load_roster(
    building_id: str, at: datetime, *, staff_user_id: str | None = None
) -> dict | None:
    with get_engine().connect() as conn:
        row = (
            conn.execute(
                _LOAD_ROSTER_SQL, {"building_id": building_id, "staff_user_id": staff_user_id}
            )
            .mappings()
            .first()
        )
        labeled = _label_rows(conn, [row]) if row else []
    return _as_roster_item(labeled[0], at) if labeled else None


def list_roster(
    context: SessionContext,
    *,
    building_id: str | None,
    staff_user_id: str | None,
    park_org_id: str | None,
    at: datetime,
) -> dict:
    """固定负责人一览：园区端看全校一栋一行，其余角色只看自己那一身班次。

    与代班列表同一道收窄：非园区强制 `staff_user_id = 当前用户`，绕过前端也读不到同事的排班。
    """
    if context.active_role.value != "CAMPUS":
        staff_user_id = context.user_id
    with get_engine().connect() as conn:
        rows = conn.execute(
            _SELECT_ROSTER_SQL,
            {
                "building_id": building_id,
                "staff_user_id": staff_user_id,
                "park_org_id": park_org_id,
            },
        ).mappings().all()
        rows = _label_rows(conn, rows)
        if park_org_id:
            rows = [row for row in rows if row["park_org_id"] == park_org_id]
        rows.sort(key=lambda row: (row["park_name"], row["building_name"], row["staff_name"]))
    return {"items": [_as_roster_item(row, at) for row in rows], "next_cursor": None}


# ------------------------------------------------------------------ 当夜代班


def grant_substitute(
    payload: Mapping[str, object], at: datetime, *, actor_user_id: str
) -> dict:
    """园区端登记代班：某人在某个业务夜多管一栋，只在班次窗口内生效。

    沿用业务基线 11-19 最终选择：无需先拥有固定值守楼栋；同栋多人、一人多栋均允许。
    """
    staff_user_id = _require_text(payload, "staff_user_id")
    building_id = _require_text(payload, "building_id")
    # `service_date` 可省：给了绝对班次就按班次所属业务夜推，没给就当作今晚，园区端不必重复填日期。
    if payload.get("service_date"):
        night = _require_date(payload, "service_date")
    elif payload.get("shift_start"):
        night = service_date_of(_parse_moment(payload["shift_start"], "shift_start"))
    else:
        night = _night_of(at)
    start, end = _window(payload, night)

    with get_engine().begin() as conn:
        _validate_subjects(conn, staff_user_id, building_id)
        inserted = conn.execute(
            _INSERT_DUTY_SQL,
            {
                "duty_id": f"duty_{uuid.uuid4().hex[:20]}",
                "staff_user_id": staff_user_id,
                "building_id": building_id,
                "service_date": night,
                "shift_start": start,
                "shift_end": end,
            },
        ).scalar()
        if inserted is None:
            raise ApiError(
                409,
                "DUTY_SLOT_TAKEN",
                "该人员在这一夜的这个楼栋已经有同一时段的代班。",
                {
                    "staff_user_id": staff_user_id,
                    "building_id": building_id,
                    "service_date": night.isoformat(),
                    "shift_start": _iso(start),
                },
            )
        _ensure_snapshot_job(conn, building_id, night)
        append_audit(
            conn,
            actor_user_id,
            "DUTY_SUBSTITUTE_GRANTED",
            str(inserted),
            {"staff_user_id": staff_user_id, "building_id": building_id, "service_date": night.isoformat()},
            at,
        )
    record = load_duty(str(inserted), at)
    assert record is not None
    return record


def revoke(payload: Mapping[str, object], at: datetime, *, actor_user_id: str) -> dict:
    """园区端撤销代班：删掉这一行的瞬间，阿姨当夜的额外范围就不再包含它。"""
    duty_id = _require_text(payload, "duty_id")
    before = load_duty(duty_id, at)
    if before is None:
        raise ApiError(
            404, "DUTY_ASSIGNMENT_NOT_FOUND", "该代班记录不存在或已撤销。", {"duty_id": duty_id}
        )
    with get_engine().begin() as conn:
        conn.execute(_DELETE_DUTY_SQL, {"duty_id": duty_id})
        append_audit(conn, actor_user_id, "DUTY_SUBSTITUTE_REVOKED", duty_id, {}, at)
    return before


def load_duty(duty_id: str, at: datetime) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(_LOAD_DUTY_SQL, {"duty_id": duty_id}).mappings().first()
        labeled = _label_rows(conn, [row]) if row else []
    return _as_duty_item(labeled[0], at) if labeled else None


def list_duties(
    context: SessionContext,
    *,
    building_id: str | None,
    staff_user_id: str | None,
    service_date: str | None,
    at: datetime,
) -> dict:
    """代班一览：园区端看全校记录，其余角色只看自己的那几条。

    固定负责人不在这里——那是名录事实，走 `list_roster`；这张表只承载按夜的临时追加。
    宿管与辅导员强制收窄到 `staff_user_id = 当前用户`，不接受客户端传别人。
    """
    if context.active_role.value != "CAMPUS":
        staff_user_id = context.user_id
    with get_engine().connect() as conn:
        rows = conn.execute(
            _SELECT_DUTY_SQL,
            {
                "staff_user_id": staff_user_id,
                "building_id": building_id,
                "service_date": service_date,
            },
        ).mappings().all()
        rows = _label_rows(conn, rows)
    return {"items": [_as_duty_item(row, at) for row in rows], "next_cursor": None}


def night_duty_map(night: date) -> dict[str, list[dict]]:
    """某一夜「楼栋 → 负责人名单」：固定在前、代班在后，园区晚归单据此列出该汇总的楼栋。

    固定班按 `valid_from/valid_to` 覆盖那一夜，班次段落回该夜的具体时刻；代班按 `service_date` 取。
    撤销会删行，所以 24:00 汇总必须把当夜名字冻结进快照，事后才答得出「某楼栋某夜谁负责」。
    """
    grouped: dict[str, list[dict]] = {}
    with get_engine().connect() as conn:
        for row in _label_rows(conn, conn.execute(_FIXED_ON_NIGHT_SQL, {"service_date": night}).mappings().all()):
            assert isinstance(row["shift_start"], time) and isinstance(row["shift_end"], time)
            shift_start, shift_end = _fixed_window(night, row["shift_start"], row["shift_end"])
            grouped.setdefault(str(row["building_id"]), []).append(
                {
                    "staff_user_id": str(row["staff_user_id"]),
                    "display_name": str(row["display_name"]),
                    "is_substitute": False,
                    "shift_start": _iso(shift_start),
                    "shift_end": _iso(shift_end),
                }
            )
        for row in _label_rows(conn, conn.execute(_SUBSTITUTE_ON_NIGHT_SQL, {"service_date": night}).mappings().all()):
            grouped.setdefault(str(row["building_id"]), []).append(
                {
                    "staff_user_id": str(row["staff_user_id"]),
                    "display_name": str(row["display_name"]),
                    "is_substitute": bool(row["is_substitute"]),
                    "shift_start": _iso(row["shift_start"]),
                    "shift_end": _iso(row["shift_end"]),
                }
            )
    return grouped


def night_roster(building_id: str, night: date) -> list[dict]:
    """某楼栋某夜的负责人（固定 + 代班），24:00 汇总时冻结进快照。"""
    return night_duty_map(night).get(building_id, [])


def fixed_watch_buildings(staff_user_id: str, at: datetime) -> list[str]:
    """查询指定人员有效固定名册楼栋，不包含账号绑楼和代班；不单独授予业务权限。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            _FIXED_BUILDING_ON_NIGHT_SQL,
            {"staff_user_id": staff_user_id, "service_date": _night_of(at)},
        ).scalars().all()
    return sorted({str(row) for row in rows})


def on_duty_buildings(staff_user_id: str, at: datetime) -> list[str]:
    """这一夜能打开今晚名单的楼栋：固定名册按业务夜整段生效，代班只在自己那段班次内生效。

    口径按 R11 的字面走：「固定值守 ∪ 当夜代班」——固定那一半只看名册的 `valid_from/valid_to`
    是否覆盖 `at` 所属的业务夜，不乘班次窗口，所以下午补录白天那条返宿记录照样能进自己那栋；
    代班是按夜的临时追加，只有 `shift_start ≤ at < shift_end` 才算范围（23:00 前打不开隔壁那栋）。
    窗口本身仍在名册行上如实报告（`on_duty_now`），供园区端看着「现在到底在岗没有」。
    """
    night = _night_of(at)
    with get_engine().connect() as conn:
        fixed = conn.execute(
            _FIXED_BUILDING_ON_NIGHT_SQL, {"staff_user_id": staff_user_id, "service_date": night}
        ).scalars().all()
        substitutes = conn.execute(
            _SUBSTITUTE_BUILDINGS_AT_SQL, {"staff_user_id": staff_user_id, "at": at}
        ).scalars().all()
    buildings = {str(row) for row in fixed}
    buildings |= {str(row) for row in substitutes}
    return sorted(buildings)


def building_duty_staff(building_id: str, at: datetime) -> list[str]:
    """这一夜这栋楼的当班人：固定名册按业务夜、代班按绝对班次区间，两条并起来才是收件人。"""
    night = _night_of(at)
    with get_engine().connect() as conn:
        fixed = conn.execute(
            _FIXED_STAFF_ON_BUILDING_SQL, {"building_id": building_id, "service_date": night}
        ).scalars().all()
        substitutes = conn.execute(
            _SUBSTITUTE_STAFF_AT_SQL, {"building_id": building_id, "at": at}
        ).scalars().all()
    staff = {str(row) for row in fixed}
    staff |= {str(row) for row in substitutes}
    return sorted(staff)


def fixed_watch_staff(building_id: str, at: datetime) -> list[str]:
    """查询某栋楼有效固定名册人员；通知与风险范围仍由目录统一出口决定。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            _FIXED_STAFF_ON_BUILDING_SQL,
            {"building_id": building_id, "service_date": _night_of(at)},
        ).scalars().all()
    return sorted({str(row) for row in rows})


def _ensure_snapshot_job(conn, building_id: str, night: date) -> None:
    """通过共享调度领域出口幂等排期，与名册/代班写入共用事务。"""
    from app.worker.scheduler import enqueue
    enqueue(conn, "DORM_TONIGHT_SNAPSHOT", f"DORM_TONIGHT_SNAPSHOT:{building_id}:{night.isoformat()}",
            {"building_id": building_id, "service_date": night.isoformat()}, summary_moment(night, _business_tz()))


__all__ = [
    "NIGHT_START_HOUR",
    "append_audit",
    "building_duty_staff",
    "fixed_watch_buildings",
    "fixed_watch_staff",
    "grant_substitute",
    "list_duties",
    "list_roster",
    "load_duty",
    "load_roster",
    "night_duty_map",
    "night_roster",
    "on_duty_buildings",
    "revoke",
    "revoke_roster",
    "set_roster",
]
