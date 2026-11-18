"""正式返宿记录领域服务（B 主责，唯一写入方）。

- 一学生一业务夜最多一条：`uq_return_per_night` 收敛并发扫码、扫码与补录竞争、回执重放（R10、场景 3）。
- 二维码核销与人工补录都只走本模块的 `confirm_return`，加入调用方事务，不各自提交（分工.md 原子边界）。
- `occurred_at` 是返宿发生时间，`recorded_at` 是记录时间；人工回填不改变发生时间。
- 未预约的手工补录同样占用当夜名额；之后到达的二维码只记重复，不再产生第二条返宿事实。
- 已过期、未确认返宿等派生状态只用于查询与报表，不生成通知任务（R15）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.clock import service_date_of
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import ApiError, out_of_scope
from app.modules.identity.schemas import SessionContext

SOURCE_QR = "QR"
SOURCE_MANUAL = "MANUAL"

_INSERT_RETURN_SQL = text(
    """
    INSERT INTO return_records (return_id, student_id, service_date, source, pass_id, gate_id,
                                occurred_at, recorded_at, evidence, idempotency_key)
    VALUES (:return_id, :student_id, :service_date, :source, :pass_id, :gate_id,
            :occurred_at, :recorded_at, CAST(:evidence AS JSONB), :idempotency_key)
    ON CONFLICT (student_id, service_date) DO NOTHING
    RETURNING return_id
    """
)

_BY_IDEMPOTENCY_SQL = text(
    "SELECT return_id FROM return_records WHERE idempotency_key = :idempotency_key"
)

_BY_NIGHT_SQL = text(
    """
    SELECT return_id FROM return_records
    WHERE student_id = :student_id AND service_date = :service_date
    """
)

_LOAD_RETURN_SQL = text(
    """
    SELECT rr.return_id, rr.student_id, rr.service_date, rr.source, rr.pass_id, rr.gate_id,
           rr.occurred_at, rr.recorded_at, rr.evidence, rr.idempotency_key,
           g.name AS gate_name, p.reservation_id
    FROM return_records rr
    LEFT JOIN gates g ON g.gate_id = rr.gate_id
    LEFT JOIN pass_codes p ON p.pass_id = rr.pass_id
    WHERE rr.return_id = :return_id
    """
)

_NIGHT_RETURNS_SQL = text(
    """
    SELECT rr.student_id, rr.return_id, rr.source, rr.occurred_at, rr.recorded_at,
           rr.gate_id, rr.pass_id, g.name AS gate_name, p.reservation_id
    FROM return_records rr
    JOIN residences res ON res.student_id = rr.student_id
        AND res.building_id = :building_id
        AND res.valid_from <= :service_date
        AND (res.valid_to IS NULL OR res.valid_to > :service_date)
    LEFT JOIN gates g ON g.gate_id = rr.gate_id
    LEFT JOIN pass_codes p ON p.pass_id = rr.pass_id
    WHERE rr.service_date = :service_date
    ORDER BY rr.occurred_at, rr.student_id
    """
)

_USAGE_SQL = text(
    """
    SELECT p.pass_id, p.student_id, p.reservation_id, p.building_id, p.gate_id,
           p.status, p.reservation_version, p.service_date,
           p.window_start, p.window_end, p.issued_at, p.expires_at, p.used_at,
           s.school_id, s.display_name,
           rr.return_id, rr.source AS return_source, rr.occurred_at
    FROM pass_codes p
    JOIN students s ON s.student_id = p.student_id
    LEFT JOIN return_records rr ON rr.pass_id = p.pass_id
    WHERE p.service_date = :service_date
      AND (CAST(:building_id AS VARCHAR) IS NULL OR p.building_id = CAST(:building_id AS VARCHAR))
    ORDER BY p.student_id, p.issued_at
    """
)

# 没有码的返宿（按门铃后人工开门等）同样要出现在返宿记录页，否则阿姨补录完查不到自己写的东西。
_CODELESS_RETURNS_SQL = text(
    """
    SELECT rr.return_id, rr.student_id, rr.service_date, rr.source, rr.gate_id,
           rr.occurred_at, s.school_id, s.display_name, res.building_id
    FROM return_records rr
    JOIN students s ON s.student_id = rr.student_id
    JOIN residences res ON res.student_id = rr.student_id
        AND res.valid_from <= rr.service_date
        AND (res.valid_to IS NULL OR res.valid_to > rr.service_date)
    WHERE rr.service_date = :service_date
      AND rr.pass_id IS NULL
      AND (CAST(:building_id AS VARCHAR) IS NULL OR res.building_id = CAST(:building_id AS VARCHAR))
    ORDER BY rr.occurred_at, rr.student_id
    """
)


def _business_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(_business_tz()).isoformat()


def new_return_id() -> str:
    return f"ret_{uuid.uuid4().hex[:20]}"


def confirm_return(
    conn: Connection,
    student_id: str,
    service_date: date | str,
    source: str,
    evidence: Mapping[str, object],
    occurred_at: datetime,
    idempotency_key: str,
    pass_id: str | None = None,
    gate_id: str | None = None,
) -> str:
    """在调用方的事务里落一条正式返宿事实，返回 return_id。

    同 `idempotency_key` 重放直接返回既有记录；当夜已有别的记录（并发扫码、
    扫码与人工补录竞争）时同样返回那条 ID，不新增第二条（场景 3）。
    """
    night = date.fromisoformat(service_date) if isinstance(service_date, str) else service_date
    replayed = conn.execute(
        _BY_IDEMPOTENCY_SQL, {"idempotency_key": idempotency_key}
    ).scalar()
    if replayed is not None:
        return str(replayed)
    inserted = conn.execute(
        _INSERT_RETURN_SQL,
        {
            "return_id": new_return_id(),
            "student_id": student_id,
            "service_date": night,
            "source": source,
            "pass_id": pass_id,
            "gate_id": gate_id,
            "occurred_at": occurred_at,
            "recorded_at": occurred_at.astimezone(_business_tz()),
            "evidence": json.dumps(dict(evidence), ensure_ascii=False),
            "idempotency_key": idempotency_key,
        },
    ).scalar()
    if inserted is not None:
        return str(inserted)
    existing = conn.execute(
        _BY_NIGHT_SQL, {"student_id": student_id, "service_date": night}
    ).scalar()
    if existing is None:
        raise ApiError(
            500,
            "INTERNAL_ERROR",
            "返宿唯一约束冲突但找不到当夜记录，请核对夜间数据。",
            {"student_id": student_id, "service_date": night.isoformat()},
        )
    return str(existing)


@contextmanager
def _transaction(conn: Connection | None):
    """`conn` 为空时自开事务，非空时加入调用方事务；跨模块不各自提交。"""
    if conn is not None:
        yield conn
        return
    with get_engine().begin() as own:
        yield own


def record_return(
    student_id: str,
    service_date: date | str,
    source: str,
    evidence: Mapping[str, object],
    occurred_at: datetime,
    idempotency_key: str,
    pass_id: str | None = None,
    gate_id: str | None = None,
    conn: Connection | None = None,
) -> dict:
    """对外入口：写入后回读整条记录，供补录接口与核销链路共用。"""
    with _transaction(conn) as active:
        return_id = confirm_return(
            active,
            student_id,
            service_date,
            source,
            evidence,
            occurred_at,
            idempotency_key,
            pass_id,
            gate_id,
        )
    record = load_record(return_id)
    assert record is not None
    return record


def load_record(return_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(_LOAD_RETURN_SQL, {"return_id": return_id}).mappings().first()
    return _as_record(row) if row else None


def _as_record(row: Mapping[str, object] | None) -> dict | None:
    if row is None:
        return None
    return {
        "return_id": row["return_id"],
        "student_id": row["student_id"],
        "service_date": str(row["service_date"]),
        "source": row["source"],
        "pass_id": row["pass_id"],
        "gate_id": row["gate_id"],
        "gate_name": row["gate_name"],
        "reservation_id": row["reservation_id"],
        "occurred_at": _iso(row["occurred_at"]),
        "recorded_at": _iso(row["recorded_at"]),
        "evidence": row["evidence"] or {},
        "idempotency_key": row["idempotency_key"],
    }


def night_records(building_id: str, service_day: date) -> list[dict]:
    """当夜该楼栋的正式返宿事实；名单只读不写。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            _NIGHT_RETURNS_SQL,
            {"building_id": building_id, "service_date": service_day},
        ).mappings().all()
    return [
        {
            "student_id": row["student_id"],
            "return_id": row["return_id"],
            "source": row["source"],
            "occurred_at": _iso(row["occurred_at"]),
            "recorded_at": _iso(row["recorded_at"]),
            "gate_id": row["gate_id"],
            "gate_name": row["gate_name"],
            "pass_id": row["pass_id"],
            "reservation_id": row["reservation_id"],
        }
        for row in rows
    ]


def records_by_student(building_id: str, service_day: date) -> dict[str, dict]:
    return {record["student_id"]: record for record in night_records(building_id, service_day)}


def _reported_status(row: Mapping[str, object], at: datetime) -> str:
    """库里仍是 ISSUED 但已过 `expires_at` 的码，在报表上算 EXPIRED；不改写库内状态。"""
    status = str(row["status"])
    expires_at = row["expires_at"]
    if status == "ISSUED" and isinstance(expires_at, datetime) and at >= expires_at:
        return "EXPIRED"
    return status


def usage_report(
    context: SessionContext, service_day: date | str | None, building_id: str | None, at: datetime
) -> dict:
    """二维码使用情况：已签发 / 已核销 / 已过期 / 已撤销，加对应的正式返宿记录。

    夜归属一律按记录自己的 `service_date`，不按墙上钟翻页：06:00 一到查询页自动切次夜，
    前一晚的码与返宿回本页看历史（R04、R12）。范围按有效值班与负责关系解析（R11）；
    过期与未确认只作派生状态，不起通知任务（R15）。
    """
    night = (
        date.fromisoformat(service_day)
        if isinstance(service_day, str)
        else service_day
        or service_date_of(at)
    )
    allowed = _scoped_students(context, at)
    allowed_buildings = _scoped_buildings(context, at)
    if building_id is not None and allowed_buildings and building_id not in allowed_buildings:
        raise out_of_scope("building", building_id, allowed_buildings)
    with get_engine().connect() as conn:
        rows = conn.execute(
            _USAGE_SQL, {"service_date": night, "building_id": building_id}
        ).mappings().all()
        codeless = conn.execute(
            _CODELESS_RETURNS_SQL, {"service_date": night, "building_id": building_id}
        ).mappings().all()

    items: list[dict] = []
    counters = {"issued": 0, "consumed": 0, "expired": 0, "revoked": 0}
    returned_students: set[str] = set()
    for row in rows:
        if allowed is not None and row["student_id"] not in allowed:
            continue
        status = _reported_status(row, at)
        counters[status.lower()] += 1
        if row["return_id"]:
            returned_students.add(str(row["student_id"]))
        items.append(
            {
                "pass_id": row["pass_id"],
                "student_id": row["student_id"],
                "school_id": row["school_id"],
                "display_name": row["display_name"],
                "reservation_id": row["reservation_id"],
                "building_id": row["building_id"],
                "gate_id": row["gate_id"],
                "reservation_version": row["reservation_version"],
                "service_date": str(row["service_date"]),
                "window_start": _iso(row["window_start"]),
                "window_end": _iso(row["window_end"]),
                "issued_at": _iso(row["issued_at"]),
                "expires_at": _iso(row["expires_at"]),
                "used_at": _iso(row["used_at"]),
                "pass_status": status,
                "return_id": row["return_id"],
                "return_source": row["return_source"],
                "returned_at": _iso(row["occurred_at"]),
            }
        )
    for row in codeless:
        if allowed is not None and row["student_id"] not in allowed:
            continue
        returned_students.add(str(row["student_id"]))
        items.append(
            {
                "pass_id": None,
                "student_id": row["student_id"],
                "school_id": row["school_id"],
                "display_name": row["display_name"],
                "reservation_id": None,
                "building_id": row["building_id"],
                "gate_id": row["gate_id"],
                "reservation_version": None,
                "service_date": str(row["service_date"]),
                "window_start": None,
                "window_end": None,
                "issued_at": None,
                "expires_at": None,
                "used_at": None,
                "pass_status": None,
                "return_id": row["return_id"],
                "return_source": row["source"],
                "returned_at": _iso(row["occurred_at"]),
            }
        )
    items.sort(key=lambda item: (item["returned_at"] or item["issued_at"] or "", item["student_id"]))
    return {
        "service_date": night.isoformat(),
        "building_id": building_id,
        "counters": {**counters, "returned": len(returned_students)},
        "items": items,
        "next_cursor": None,
    }


def _scoped_students(context: SessionContext, at: datetime) -> list[str] | None:
    """辅导员只看负责学生；宿管与园区不按学生过滤，负责关系缺失时按空范围处理。"""
    if context.active_role.value != "COUNSELOR":
        return None
    return [str(student_id) for student_id in context.scope.get("student_ids") or []]


def _scoped_buildings(context: SessionContext, at: datetime) -> list[str]:
    if context.active_role.value != "DORM_MANAGER":
        return []
    return [str(building_id) for building_id in context.scope.get("building_ids") or []]


def manual_record(context: SessionContext, payload: Mapping[str, object], at: datetime) -> dict:
    """宿管人工补录（R11）：按门铃等实际返宿情况，只走统一入口 `confirm_return`。

    `occurred_at` 是宿管填报的发生时间，服务端校验它落在所声称的业务夜区间内且不未来；
    `recorded_at` 另存为记录时间。补录同样占用当夜名额，之后二维码扫码只记重复，不再补第二条。
    """
    student_id = _text_field(payload, "student_id")
    building_id = _text_field(payload, "building_id")
    allowed_buildings = _scoped_buildings(context, at)
    if allowed_buildings and building_id not in allowed_buildings:
        raise out_of_scope("building", building_id, allowed_buildings)
    night = (
        date.fromisoformat(str(payload["service_date"]))
        if payload.get("service_date")
        else service_date_of(at)
    )
    occurred = _moment_field(payload, "occurred_at", at)
    if occurred > at:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "补录的发生时间不能晚于当前服务端时间。",
            {"occurred_at": _iso(occurred)},
        )
    if service_date_of(occurred) != night:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "发生时间与所填业务夜不属于同一夜。",
            {
                "occurred_at": _iso(occurred),
                "service_date": night.isoformat(),
                "rule": "业务日 D = [D 06:00, D+1 06:00)",
            },
        )
    gate_id = payload.get("gate_id")
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, Mapping):
        raise ApiError(
            422, "VALIDATION_FAILED", "补录证据必须是对象。", {"field": "evidence"}
        )
    with get_engine().begin() as conn:
        return_id = confirm_return(
            conn,
            student_id=student_id,
            service_date=night,
            source=SOURCE_MANUAL,
            evidence={**evidence, "recorded_by": context.user_id, "building_id": building_id},
            occurred_at=occurred,
            idempotency_key=str(payload.get("idempotency_key") or f"manual:{uuid.uuid4().hex}"),
            gate_id=str(gate_id) if gate_id else None,
        )
    record = load_record(return_id)
    assert record is not None
    return record


def _text_field(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ApiError(
            422, "VALIDATION_FAILED", f"补录缺少字段 {name}。", {"missing": name}
        )
    return value


def _moment_field(payload: Mapping[str, object], name: str, at: datetime) -> datetime:
    value = payload.get(name)
    if value is None:
        return at
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


__all__ = [
    "SOURCE_MANUAL",
    "SOURCE_QR",
    "confirm_return",
    "load_record",
    "manual_record",
    "night_records",
    "record_return",
    "records_by_student",
    "usage_report",
]
