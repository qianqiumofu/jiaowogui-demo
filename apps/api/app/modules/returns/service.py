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

from app.core.clock import service_date_of, build_clock
from app.core.config import get_settings
from app.core.night_lock import lock_night
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




# 没有码的返宿（按门铃后人工开门等）同样要出现在返宿记录页，否则阿姨补录完查不到自己写的东西。


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
    recorded_at: datetime | None = None,
) -> str:
    """在调用方的事务里落一条正式返宿事实，返回 return_id。

    同 `idempotency_key` 重放直接返回既有记录；当夜已有别的记录（并发扫码、
    扫码与人工补录竞争）时同样返回那条 ID，不新增第二条（场景 3）。
    """
    night = date.fromisoformat(service_date) if isinstance(service_date, str) else service_date
    lock_night(conn, student_id, night)
    replayed = conn.execute(
        _BY_IDEMPOTENCY_SQL, {"idempotency_key": idempotency_key}
    ).scalar()
    if replayed is not None:
        owner=conn.execute(text("SELECT student_id,service_date FROM return_records WHERE return_id=:r"),{"r":replayed}).one()
        if owner.student_id!=student_id or owner.service_date!=night:
            raise ApiError(409,"VERSION_CONFLICT","幂等键已用于不同学生或业务夜。",{})
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
            "recorded_at": (recorded_at or build_clock().now()).astimezone(_business_tz()),
            "evidence": json.dumps(dict(evidence), ensure_ascii=False),
            "idempotency_key": idempotency_key,
        },
    ).scalar()
    if inserted is not None:
        from app.modules.reservation.service import fulfill_night
        fulfill_night(conn, student_id, night, str(inserted))
        add_evidence(conn,str(inserted),idempotency_key,source,dict(evidence),recorded_at or build_clock().now())
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
    add_evidence(conn,str(existing),idempotency_key,source,dict(evidence),recorded_at or build_clock().now())
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
        record = load_record(return_id,active)
        assert record is not None
    return record


def load_record(return_id: str, conn=None) -> dict | None:
    if conn is None:
        with get_engine().connect() as own:return load_record(return_id,own)
    row=conn.execute(text("SELECT * FROM return_records WHERE return_id=:r"),{"r":return_id}).mappings().first()
    if row is None:return None
    from app.modules.directory.service import gate_names
    from app.modules.access.service import reservation_for_pass
    return _as_record({**dict(row),"gate_name":gate_names(conn).get(row["gate_id"]),"reservation_id":reservation_for_pass(conn,row["pass_id"])})


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
    from app.modules.directory.service import return_labels,gate_names
    from app.modules.access.service import reservation_for_pass
    with get_engine().connect() as conn:
        labels=return_labels(conn,service_day);gates=gate_names(conn)
        rows=conn.execute(text("SELECT * FROM return_records WHERE service_date=:n ORDER BY occurred_at,student_id"),{"n":service_day}).mappings()
        return [{"student_id":r["student_id"],"return_id":r["return_id"],"source":r["source"],"occurred_at":_iso(r["occurred_at"]),"recorded_at":_iso(r["recorded_at"]),"gate_id":r["gate_id"],"gate_name":gates.get(r["gate_id"]),"pass_id":r["pass_id"],"reservation_id":reservation_for_pass(conn,r["pass_id"])} for r in rows if labels.get(r["student_id"],{}).get("building_id")==building_id]


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
    from app.modules.directory.service import return_labels
    from app.modules.access.service import usage_rows
    with get_engine().connect() as conn:
        labels=return_labels(conn,night)
        formal=[dict(r) for r in conn.execute(text("SELECT * FROM return_records WHERE service_date=:n"),{"n":night}).mappings()]
        by_pass={r["pass_id"]:r for r in formal if r["pass_id"]}
        rows=[]
        for code in usage_rows(conn,night,building_id):
            info=labels.get(code["student_id"],{})
            returned=by_pass.get(code["pass_id"],{})
            rows.append({**code,"school_id":info.get("school_id","目录未同步"),"display_name":info.get("display_name",code["student_id"]),"return_id":returned.get("return_id"),"return_source":returned.get("source"),"occurred_at":returned.get("occurred_at")})
        codeless=[{**r,**labels.get(r["student_id"],{})} for r in formal if r["pass_id"] is None and (building_id is None or labels.get(r["student_id"],{}).get("building_id")==building_id)]

    items: list[dict] = []
    counters = {"issued": 0, "consumed": 0, "expired": 0, "revoked": 0}
    returned_students: set[str] = set()
    for row in rows:
        if allowed is not None and row["student_id"] not in allowed:
            continue
        if context.active_role.value == "DORM_MANAGER" and row["building_id"] not in allowed_buildings:
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
        if context.active_role.value == "DORM_MANAGER" and row["building_id"] not in allowed_buildings:
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
    if context.active_role.value not in ("COUNSELOR","IDEOLOGY","COLLEGE_ADMIN","STUDENT"):
        return None
    if context.active_role.value=="STUDENT":return [str(context.scope.get("student_id"))]
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
    if building_id not in allowed_buildings:
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
    from app.modules.directory.service import get_residence
    residence = get_residence(student_id, occurred)
    if residence is None or residence["building_id"] != building_id:
        raise out_of_scope("student", student_id, allowed_buildings)
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
            recorded_at=at,
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


def find_for_night(conn: Connection, student_id: str, service_date: date) -> str | None:
    value = conn.execute(_BY_NIGHT_SQL, {"student_id": student_id, "service_date": service_date}).scalar()
    return str(value) if value else None


def returned_keys(conn: Connection, start: date, end: date) -> set[tuple[str, date]]:
    return {(r.student_id, r.service_date) for r in conn.execute(text("SELECT student_id, service_date FROM return_records WHERE service_date BETWEEN :start AND :end"), {"start": start, "end": end})}


def scoped_record(context,return_id,at):
    from app.core.errors import ApiError
    record=load_record(return_id)
    if record is None:raise ApiError(404,"SUBJECT_NOT_FOUND","正式记录不存在。",{})
    if context.active_role.value=="DORM_MANAGER":
        from app.modules.directory.service import get_residence
        home=get_residence(record["student_id"],datetime.fromisoformat(record["occurred_at"]))
        if home is None or home["building_id"] not in context.scope.get("building_ids",[]):
            raise ApiError(403,"OUT_OF_SCOPE","记录不在值班范围。",{})
    elif record["student_id"] not in context.scope.get("student_ids",[context.scope.get("student_id")]):
        raise ApiError(403,"OUT_OF_SCOPE","记录不在负责范围。",{})
    return record


def corrections(context,return_id,at):
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from app.db.models import ReturnCorrection
    scoped_record(context,return_id,at)
    with Session(get_engine()) as db:
        rows=list(db.scalars(select(ReturnCorrection).where(ReturnCorrection.return_id==return_id).order_by(ReturnCorrection.created_at)))
        return {"items":[{"id":r.id,"note":r.note,"occurred_at":r.occurred_at,"created_at":r.created_at,"actor_user_id":r.actor_user_id} for r in rows],"next_cursor":None}


def correct(context,return_id,note,occurred_at,at):
    from sqlalchemy.orm import Session
    from app.db.models import ReturnCorrection
    from app.core.audit import append as audit
    record=scoped_record(context,return_id,at)
    if not note.strip() or len(note)>500:raise ApiError(422,"VALIDATION_FAILED","更正说明需要 1—500 字符。",{})
    if occurred_at and (occurred_at>at or service_date_of(occurred_at).isoformat()!=record["service_date"]):
        raise ApiError(422,"VALIDATION_FAILED","更正时间必须属于原业务夜且不能是未来。",{})
    with Session(get_engine()) as db:
        row=ReturnCorrection(id="corr_"+uuid.uuid4().hex[:24],return_id=return_id,actor_user_id=context.user_id,note=note,occurred_at=occurred_at,created_at=at)
        db.add(row);audit(db,context.user_id,"RETURN_CORRECTED",return_id,{"note":note,"occurred_at":occurred_at.isoformat() if occurred_at else None},at);db.commit()
        return {"id":row.id,"return_id":return_id,"note":note,"occurred_at":occurred_at,"created_at":at,"original_preserved":True}


def fact_nights(start,end):
    from collections import defaultdict
    result=defaultdict(list)
    with get_engine().connect() as conn:
        for row in conn.execute(text("SELECT student_id,service_date FROM return_records WHERE service_date BETWEEN :s AND :e ORDER BY service_date"),{"s":start,"e":end}):
            result[row.student_id].append(row.service_date)
    return dict(result)


def add_evidence(conn,return_id,key,kind,payload,at):
    conn.execute(text("INSERT INTO return_evidence(id,return_id,source_key,kind,payload,created_at) VALUES(:id,:r,:key,:kind,CAST(:data AS jsonb),:at) ON CONFLICT(source_key) DO NOTHING"),{"id":"ev_"+uuid.uuid4().hex,"r":return_id,"key":key,"kind":kind,"data":json.dumps(payload,ensure_ascii=False),"at":at})


def evidence(context,return_id,at):
    scoped_record(context,return_id,at)
    with get_engine().connect() as conn:
        rows=conn.execute(text("SELECT id,kind,payload,created_at FROM return_evidence WHERE return_id=:r ORDER BY created_at,id"),{"r":return_id}).mappings().all()
        return {"items":[dict(r) for r in rows],"next_cursor":None}


def statistic_rows(conn,start,end):
    return [dict(r) for r in conn.execute(text("SELECT student_id,service_date,source FROM return_records WHERE service_date BETWEEN :s AND :e"),{"s":start,"e":end}).mappings()]


def record_for_pass(conn,pass_id):
    row=conn.execute(text("SELECT return_id,source,occurred_at,student_id,service_date,pass_id FROM return_records WHERE pass_id=:p"),{"p":pass_id}).mappings().first()
    return dict(row) if row else None


def record_for_night(conn,student_id,night):
    row=conn.execute(text("SELECT return_id,source,occurred_at,student_id,service_date,pass_id FROM return_records WHERE student_id=:s AND service_date=:n"),{"s":student_id,"n":night}).mappings().first()
    return dict(row) if row else None
