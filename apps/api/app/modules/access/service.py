"""夜行通行码领域服务（B 主责）：签发、撤销、核销与设备身份。

- 核验结果与预约版本、学生、楼栋、门点绑定，一次使用；改期与撤销先作废旧码再签新码
  （R08、基线「同一预约最多一个有效码」）。签码入口只由 A 的核验链路调用，不开放绕过核验的领码接口。
- 二维码自签发起有效 `pass_ttl_seconds` 秒（R09，Demo 配置）；过期只能重新核验再签，
  刷新旧码不延长有效期。
- 夜间通行授权只允许 [00:00,06:00)（R04）；时段结束后终端返回 NIGHT_ACCESS_ENDED，转学校正常通行流程。
- 成功核销在同一个事务里落正式返宿事实，写入只走 returns.confirm_return（R10）。
- 终端按设备身份鉴权：库里只存令牌摘要，明文只在签发响应中出现一次。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.clock import build_clock, is_night_gate, service_date_of
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import ApiError
from app.modules.returns import service as returns

STATUS_CONSUMED = "CONSUMED"
STATUS_REVOKED = "REVOKED"

GRANT_FIELDS = (
    "student_id",
    "building_id",
    "verification_id",
    "planned_return_at",
    "window_start",
    "window_end",
    "verified_at",
)

_INSERT_PASS_SQL = text(
    """
    INSERT INTO pass_codes (pass_id, reservation_id, student_id, building_id, gate_id,
                               verification_id, reservation_version, token_digest,
                               service_date, window_start, window_end,
                               issued_at, expires_at, status)
    VALUES (:pass_id, :reservation_id, :student_id, :building_id, :gate_id,
            :verification_id, :reservation_version, :token_digest,
            :service_date, :window_start, :window_end,
            :issued_at, :expires_at, 'ISSUED')
    """
)

_REVOKE_ACTIVE_SQL = text(
    """
    UPDATE pass_codes SET status = 'REVOKED'
    WHERE reservation_id = :reservation_id AND status = 'ISSUED'
    """
)

_LOCK_PASS_SQL = text(
    """
    SELECT p.pass_id, p.student_id, p.building_id, p.gate_id, p.status, p.service_date,
           p.window_start, p.window_end, p.expires_at, p.issued_at, p.reservation_id,
           p.verification_id, d.gate_id AS device_gate_id, g.name AS device_gate_name
    FROM pass_codes p
    JOIN devices d ON d.device_id = :device_id
    JOIN gates g ON g.gate_id = d.gate_id
    WHERE p.token_digest = :token_digest
    """
)

_CONSUME_SQL = text(
    """
    UPDATE pass_codes SET status = 'CONSUMED', used_at = :used_at
    WHERE pass_id = :pass_id AND status = 'ISSUED'
    """
)

_MARK_EXPIRED_SQL = text(
    """
    UPDATE pass_codes SET status = 'EXPIRED'
    WHERE pass_id = :pass_id AND status = 'ISSUED'
    """
)

_NIGHT_RECORD_SQL = text(
    """
    SELECT return_id, source, pass_id, occurred_at
    FROM return_records
    WHERE student_id = :student_id AND service_date = :service_date
    """
)

_RECORD_BY_PASS_SQL = text(
    """
    SELECT return_id, source, occurred_at
    FROM return_records
    WHERE pass_id = :pass_id
    """
)

_DEVICE_SQL = text(
    """
    SELECT d.device_id, d.token_digest, d.gate_id, g.building_id, g.name AS gate_name
    FROM devices d
    JOIN gates g ON g.gate_id = d.gate_id
    WHERE d.device_id = :device_id
    """
)


def _business_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(_business_tz()).isoformat()


def _parse(moment: str | datetime) -> datetime:
    return datetime.fromisoformat(moment) if isinstance(moment, str) else moment


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_pass_id() -> str:
    return f"pass_{uuid.uuid4().hex[:20]}"


def _grant_field(grant: Mapping[str, object], name: str) -> str:
    value = grant.get(name)
    if not isinstance(value, str) or not value:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "核验凭证缺少必要字段，无法签码。",
            {"missing": name, "capability": "access.issue_pass"},
        )
    return value


def issue_pass(reservation_id: str, version: int, grant: Mapping[str, object]) -> dict:
    """A 的核验成功后调用：先作废旧码，再按预约版本签一条新码。

    返回的 `token` 是库里唯一一次出现的明文；库内只存摘要，过期时刻按
    `pass_ttl_seconds`（R09）从核验时刻起算，不由客户端决定。
    """
    student_id = _grant_field(grant, "student_id")
    building_id = _grant_field(grant, "building_id")
    verification_id = _grant_field(grant, "verification_id")
    verified_at = _parse(_grant_field(grant, "verified_at"))
    window_start = _parse(_grant_field(grant, "window_start"))
    window_end = _parse(_grant_field(grant, "window_end"))
    planned_return_at = _parse(_grant_field(grant, "planned_return_at"))
    service_day = service_date_of(planned_return_at)
    gate_id = grant.get("gate_id")
    expires_at = verified_at + timedelta(seconds=get_settings().pass_ttl_seconds)
    token = secrets.token_urlsafe(32)

    with get_engine().begin() as conn:
        conn.execute(_REVOKE_ACTIVE_SQL, {"reservation_id": reservation_id})
        pass_id = new_pass_id()
        conn.execute(
            _INSERT_PASS_SQL,
            {
                "pass_id": pass_id,
                "reservation_id": reservation_id,
                "student_id": student_id,
                "building_id": building_id,
                "gate_id": gate_id,
                "verification_id": verification_id,
                "reservation_version": version,
                "token_digest": token_digest(token),
                "service_date": service_day,
                "window_start": window_start,
                "window_end": window_end,
                "issued_at": verified_at,
                "expires_at": expires_at,
            },
        )
    return {
        "pass_id": pass_id,
        "token": token,
        "building_id": building_id,
        "gate_id": gate_id,
        "service_date": service_day.isoformat(),
        "reservation_version": version,
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "issued_at": _iso(verified_at),
        "expires_at": _iso(expires_at),
    }


def revoke_passes(reservation_id: str) -> int:
    """改期、撤销或住宿失效时作废旧码：返回被撤销的条数，新码须基于新的现场核验。"""
    with get_engine().begin() as conn:
        result = conn.execute(_REVOKE_ACTIVE_SQL, {"reservation_id": reservation_id})
    return int(result.rowcount or 0)


def authenticate_device(device_id: str, token: str) -> dict:
    """终端身份：比对令牌摘要；不匹配按鉴权失败处理，不透露该码是否存在。"""
    with get_engine().connect() as conn:
        row = conn.execute(_DEVICE_SQL, {"device_id": device_id}).mappings().first()
    if row is None:
        raise ApiError(
            401,
            "DEVICE_UNKNOWN",
            "终端未登记，拒绝核销。",
            {"device_id": device_id},
        )
    if not isinstance(token, str) or not hmac.compare_digest(
        str(row["token_digest"]), token_digest(token)
    ):
        raise ApiError(
            401,
            "DEVICE_UNAUTHORIZED",
            "终端令牌校验失败，拒绝核销。",
            {"device_id": device_id},
        )
    return dict(row)


def _attempt(pass_id: str, device: Mapping[str, object], at: datetime) -> dict:
    return {
        "attempt_status": "SUCCEEDED",
        "pass_id": pass_id,
        "duplicate": False,
        "device_id": str(device["device_id"]),
        "building_id": str(device["building_id"]),
        "gate_id": str(device["gate_id"]),
        "gate_name": device["gate_name"],
        "occurred_at": _iso(at),
    }


def _preflight(device: dict, device_id: str, code: str, moment: datetime) -> dict:
    """只读校验并返回当次扫码所需信息；过期标记要独立提交，所以判定与写入分两段。"""
    with get_engine().connect() as conn:
        row = conn.execute(
            _LOCK_PASS_SQL, {"device_id": device_id, "token_digest": token_digest(code)}
        ).mappings().first()
        if row is None:
            raise ApiError(
                404,
                "PASS_NOT_FOUND",
                "二维码无效或不存在，请重新核验领码。",
                {"device_id": device_id},
            )
        if str(row["building_id"]) != str(device["building_id"]) or (
            row["gate_id"] is not None and str(row["gate_id"]) != str(device["gate_id"])
        ):
            raise ApiError(
                403,
                "GATE_MISMATCH",
                "二维码与本终端的门禁范围不一致。",
                {
                    "pass_building_id": row["building_id"],
                    "device_building_id": device["building_id"],
                    "pass_gate_id": row["gate_id"],
                    "device_gate_id": device["gate_id"],
                },
            )
        if row["status"] == STATUS_REVOKED:
            raise ApiError(
                409,
                "PASS_REVOKED",
                "该码已随改期或撤销作废，请重新核验领码。",
                {"pass_id": row["pass_id"]},
            )
        replayed = None
        if row["status"] == STATUS_CONSUMED:
            replayed = conn.execute(
                _RECORD_BY_PASS_SQL, {"pass_id": row["pass_id"]}
            ).mappings().first()
            if replayed is None:
                raise ApiError(
                    500,
                    "INTERNAL_ERROR",
                    "该码已核销但找不到对应的正式返宿记录，请核对当夜数据。",
                    {"pass_id": row["pass_id"]},
                )
        if moment >= row["expires_at"]:
            _mark_expired(str(row["pass_id"]))
            raise ApiError(
                410,
                "PASS_EXPIRED",
                "二维码已超过有效期，必须重新核验领码。",
                {"pass_id": row["pass_id"], "expires_at": _iso(row["expires_at"])},
            )
        if not is_night_gate(moment):
            raise ApiError(
                403,
                "NIGHT_ACCESS_ENDED",
                "夜间通行授权时段已结束，转学校正常通行流程。",
                {
                    "pass_id": row["pass_id"],
                    "service_date": str(row["service_date"]),
                    "gate_window": "[00:00,06:00)",
                },
            )
        existing = conn.execute(
            _NIGHT_RECORD_SQL,
            {"student_id": row["student_id"], "service_date": row["service_date"]},
        ).mappings().first()
        if existing is not None and replayed is None:
            raise ApiError(
                409,
                "RETURN_EXISTS",
                "该业务夜已有正式返宿记录，本次扫码不放行。",
                {
                    "return_id": existing["return_id"],
                    "source": existing["source"],
                    "service_date": str(row["service_date"]),
                },
            )
        return {
            "pass": dict(row),
            "replay": dict(replayed) if replayed is not None else None,
        }


def _mark_expired(pass_id: str) -> None:
    """过期状态单独提交：拒绝本次放行之时，作废标记要留下来（R09）。"""
    with get_engine().begin() as conn:
        conn.execute(_MARK_EXPIRED_SQL, {"pass_id": pass_id})


def consume(device_id: str, device_token: str, code: str, at: datetime | None = None) -> dict:
    """终端扫码核销：设备鉴权、门禁绑定、时段与唯一性都服务端判定。

    重复扫码与回执重放最多形成一个当夜返宿事件（场景 3）：同一条码再次扫码只返回
    既有记录，不再补一条。当夜已有别的来源（如人工补录）的返宿事实时拒绝放行，
    返回 RETURN_EXISTS，二维码不占用第二次名额。
    """
    device = authenticate_device(device_id, device_token)
    moment = at or build_clock().now()
    outcome = _preflight(device, device_id, code, moment)
    pass_row, replay = outcome["pass"], outcome["replay"]
    if replay is not None:
        return {
            **_attempt(pass_row["pass_id"], device, moment),
            "duplicate": True,
            "return_id": replay["return_id"],
            "return_source": replay["source"],
            "occurred_at": _iso(replay["occurred_at"]),
        }

    with get_engine().begin() as conn:
        consumed = conn.execute(
            _CONSUME_SQL, {"pass_id": pass_row["pass_id"], "used_at": moment}
        )
        if not consumed.rowcount:
            raise ApiError(
                409,
                "PASS_CONSUMED",
                "同一码被并发扫码占用，本次不重复放行。",
                {"pass_id": pass_row["pass_id"]},
            )
        return_id = returns.confirm_return(
            conn,
            student_id=pass_row["student_id"],
            service_date=pass_row["service_date"],
            source=returns.SOURCE_QR,
            evidence={
                "device_id": device_id,
                "gate_id": device["gate_id"],
                "pass_id": pass_row["pass_id"],
                "verification_id": pass_row["verification_id"],
            },
            occurred_at=moment,
            idempotency_key=f"qr:{pass_row['pass_id']}",
            pass_id=pass_row["pass_id"],
            gate_id=str(device["gate_id"]),
        )
    return {**_attempt(pass_row["pass_id"], device, moment), "return_id": return_id}


__all__ = [
    "STATUS_CONSUMED",
    "STATUS_REVOKED",
    "authenticate_device",
    "consume",
    "issue_pass",
    "new_pass_id",
    "revoke_passes",
    "token_digest",
]
