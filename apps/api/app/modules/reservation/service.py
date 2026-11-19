"""预约领域服务（A 主责）。规则来源：R05/R06/R07 与基线「统一日期与边界」。

- 一晚一条：(student_id, service_date) 唯一，冲突由数据库约束兜底并映射为 409。
- 全部自动通过（R06）；原因只作长度校验（Demo 默认配置），不作为拒绝依据。
- 改期不限次数（R07）；业务夜结束（次日 06:00）后一律不可修改，读取时惰性置 CLOSED。
- 取消保留 ID，恢复复用同一 ID；已返宿（FULFILLED）不可取消/修改。
- 跨模块约定：B 的返宿模块经 mark_fulfilled 消费预约；本模块不写 night_returns。
"""

from __future__ import annotations

import secrets
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import NIGHT_GATE_END_MINUTE, Clock, service_date_of, is_summary_passed, summary_moment, business_iso
from app.core.config import get_settings
from app.core.night_lock import lock_night
from app.core.errors import ApiError
from app.db.models import Reservation, ReservationRevision


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def night_bounds(service_date: date, tz) -> tuple[datetime, datetime]:
    """门禁时段 [D+1 00:00, D+1 06:00)，端点包含下界（R04）。"""
    start = datetime.combine(service_date + timedelta(days=1), datetime.min.time(), tz)
    end = datetime.combine(service_date + timedelta(days=1), datetime.min.time(), tz) + timedelta(
        minutes=NIGHT_GATE_END_MINUTE
    )
    return start, end


def latest_return_at(service_date: date, tz) -> datetime:
    """最晚可选返宿时刻 = 门禁结束 - 核验窗口半径（默认 06:00-30min=05:30）。

    这样预约时刻 ±margin 的核验窗口不会越过 06:00，06:00 后不再核验、不再签发
    立刻作废的晚归码（R04 门禁 06:00 恢复正常通行，用户 2026-11-19 确认）。
    """
    _, end = night_bounds(service_date, tz)
    return end - timedelta(minutes=get_settings().verification_margin_minutes)


def _assert_in_window(planned: datetime, service_date: date, tz) -> None:
    start, end = night_bounds(service_date, tz)
    latest = latest_return_at(service_date, tz)
    # 上界收到 latest（含），保证核验窗口落在门禁时段内，不在 06:00 后产出废码。
    if not (start <= planned <= latest):
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "返宿目标时间必须位于该业务夜的夜间门禁时段内，且不晚于最晚可选时刻（门禁结束前一个核验窗口）。",
            {
                "planned_return_at": planned.isoformat(),
                "night_window": [start.isoformat(), end.isoformat()],
                "latest_return_at": latest.isoformat(),
            },
        )


def _assert_reason(reason: str) -> None:
    limit = get_settings().reservation_reason_max_chars
    if len(reason) > limit:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            f"原因文本超过 {limit} 字符上限（Demo 默认，非校规）。",
            {"field": "reason", "max_length": limit},
        )


def _status_conflict(res: Reservation) -> ApiError:
    if res.status == "CANCELLED":
        return ApiError(
            409,
            "RESERVATION_CANCELLED",
            "当夜预约已取消，请使用恢复接口复用原预约。",
            {"reservation_id": res.id, "status": res.status, "version": res.version},
        )
    return ApiError(
        409,
        "RESERVATION_EXISTS",
        "当夜已存在预约；一晚只允许一条。",
        {"reservation_id": res.id, "status": res.status, "version": res.version},
    )


def _append_revision(
    session: Session, res: Reservation, source: str, changed_by: str | None, at: datetime
) -> None:
    session.add(
        ReservationRevision(
            id=new_id("rev"),
            reservation_id=res.id,
            version=res.version,
            source=source,
            status=res.status,
            planned_return_at=res.planned_return_at,
            reason=res.reason,
            changed_by=changed_by,
            changed_at=at,
        )
    )


def create_reservation(
    session: Session,
    clock: Clock,
    *,
    student_id: str,
    school_id: str,
    actor_user_id: str,
    planned_return_at: datetime,
    reason: str,
) -> Reservation:
    now = clock.now()
    service_date = service_date_of(now)
    _assert_in_window(planned_return_at, service_date, now.tzinfo)
    _assert_reason(reason)

    lock_night(session.connection(), student_id, service_date)
    from app.modules.returns.service import find_for_night
    returned = find_for_night(session.connection(), student_id, service_date)
    if returned is not None:
        raise ApiError(409, "RETURN_EXISTS", "该业务夜已有正式返宿记录，不可再次预约放行。", {"return_id": returned})
    if is_summary_passed(now, service_date):
        raise ApiError(409, "RESERVATION_CREATION_CLOSED", "该业务夜首次申请已截止，已有预约仍可改期与撤销。", {"service_date": service_date.isoformat(), "closes_at": business_iso(summary_moment(service_date, now.tzinfo))})

    existing = session.scalar(
        select(Reservation)
        .where(Reservation.student_id == student_id, Reservation.service_date == service_date)
        .with_for_update()
    )
    if existing is not None:
        raise _status_conflict(existing)

    res = Reservation(
        id=new_id("resv"),
        student_id=student_id,
        school_id=school_id,
        service_date=service_date,
        status="ACTIVE",
        planned_return_at=planned_return_at,
        reason=reason,
        version=1,
        created_at=now,updated_at=now,
    )
    try:
        session.add(res)
        session.flush()
        _append_revision(session, res, "CREATE", actor_user_id, clock.now())
        _queue_change(session, clock, res, "APPROVED")
        session.commit()
    except IntegrityError:
        # 并发创建：唯一约束只放行一条；等对手事务可见后返回同样的冲突。
        session.rollback()
        raced = None
        for _ in range(40):
            raced = session.scalar(
                select(Reservation).where(
                    Reservation.student_id == student_id, Reservation.service_date == service_date
                )
            )
            if raced is not None:
                break
            time.sleep(0.05)
        if raced is None:
            raise ApiError(500, "INTERNAL_ERROR", "唯一约束冲突但找不到已存在预约。", {}) from None
        raise _status_conflict(raced) from None
    return res


def close_finished_nights(session: Session, clock: Clock, student_id: str | None = None) -> None:
    """业务夜已结束的 ACTIVE 预约置 CLOSED，并追加系统修订。"""
    current = service_date_of(clock.now())
    query = select(Reservation).where(
        Reservation.status == "ACTIVE", Reservation.service_date < current
    )
    if student_id is not None:
        query = query.where(Reservation.student_id == student_id)
    for res in session.scalars(query.with_for_update()):
        res.status = "CLOSED"
        _append_revision(session, res, "CLOSE", None, clock.now())
    session.commit()


def _load_owned(
    session: Session, clock: Clock, *, reservation_id: str, scope: dict, resolved_by: str
) -> Reservation:
    if resolved_by.startswith("pending:"):
        raise _scope_unresolved(scope)
    identity = session.get(Reservation, reservation_id)
    if identity is not None:
        lock_night(session.connection(), identity.student_id, identity.service_date)
    res = session.get(Reservation, reservation_id, with_for_update=True, populate_existing=True)
    if res is None or not _in_scope(res, scope):
        raise ApiError(
            404, "RESERVATION_NOT_FOUND", "预约不存在或不在当前数据范围内。", {"reservation_id": reservation_id}
        )
    if res.status == "ACTIVE" and res.service_date < service_date_of(clock.now()):
        res.status = "CLOSED"
        _append_revision(session, res, "CLOSE", None, clock.now())
        session.commit()
    return res


def _scope_unresolved(scope: dict) -> ApiError:
    return ApiError(
        403,
        "SCOPE_UNRESOLVED",
        "数据范围依赖的目录关系尚未同步，无法按范围查询预约。",
        {"action": "reservation:read", "resolved_by": scope.get("resolved_by", "unknown")},
    )


def _in_scope(res: Reservation, scope: dict) -> bool:
    if "student_id" in scope:
        return res.student_id == scope["student_id"]
    if "student_ids" in scope:
        return res.student_id in scope["student_ids"]
    if scope.get("scope") == "ALL_AUTHORIZED":
        return True
    if "building_ids" in scope:
        from app.modules.directory.service import get_residence
        residence = get_residence(res.student_id, res.planned_return_at)
        return residence is not None and residence["building_id"] in scope["building_ids"]
    return False


def tonight(session: Session, clock: Clock, *, student_id: str) -> Reservation | None:
    """当前业务夜本人预约；service_date 一律由服务端时钟判定。"""
    close_finished_nights(session, clock, student_id)
    return session.scalar(
        select(Reservation).where(
            Reservation.student_id == student_id,
            Reservation.service_date == service_date_of(clock.now()),
        )
    )


def list_reservations(
    session: Session, clock: Clock, *, scope: dict, service_date: date | None
) -> list[Reservation]:
    if str(scope.get("resolved_by", "")).startswith("pending:"):
        raise _scope_unresolved(scope)
    student_id = scope.get("student_id")
    if student_id is not None:
        close_finished_nights(session, clock, student_id)
    query = select(Reservation).order_by(Reservation.service_date.desc(), Reservation.id)
    if "student_id" in scope:
        query = query.where(Reservation.student_id == scope["student_id"])
    elif "student_ids" in scope:
        query = query.where(Reservation.student_id.in_(scope["student_ids"]))
    if service_date is not None:
        query = query.where(Reservation.service_date == service_date)
    items = list(session.scalars(query))
    return [res for res in items if _in_scope(res, scope)]


def _assert_mutable(res: Reservation, expected_version: int) -> None:
    if res.status != "ACTIVE":
        raise ApiError(
            409,
            "RESERVATION_NOT_EDITABLE",
            "当前状态不允许修改该预约。",
            {"reservation_id": res.id, "status": res.status},
        )
    if res.version != expected_version:
        raise ApiError(
            409,
            "VERSION_CONFLICT",
            "预约已被更新，请重新获取最新版本。",
            {"expected_version": expected_version, "current_version": res.version},
        )


def reschedule(
    session: Session,
    clock: Clock,
    *,
    reservation_id: str,
    scope: dict,
    resolved_by: str,
    actor_user_id: str,
    expected_version: int,
    planned_return_at: datetime | None,
    reason: str | None,
) -> Reservation:
    res = _load_owned(session, clock, reservation_id=reservation_id, scope=scope, resolved_by=resolved_by)
    _assert_mutable(res, expected_version)
    if planned_return_at is not None:
        _assert_in_window(planned_return_at, res.service_date, clock.now().tzinfo)
        res.planned_return_at = planned_return_at
    if reason is not None:
        _assert_reason(reason)
        res.reason = reason
    res.version += 1
    res.updated_at=clock.now()
    _append_revision(session, res, "RESCHEDULE", actor_user_id, clock.now())
    from app.modules.access.service import revoke_passes
    revoke_passes(res.id, conn=session.connection())
    _queue_change(session, clock, res, "RESCHEDULED")
    session.commit()
    return res


def cancel(
    session: Session,
    clock: Clock,
    *,
    reservation_id: str,
    scope: dict,
    resolved_by: str,
    actor_user_id: str,
    expected_version: int,
) -> Reservation:
    res = _load_owned(session, clock, reservation_id=reservation_id, scope=scope, resolved_by=resolved_by)
    _assert_mutable(res, expected_version)
    res.status = "CANCELLED"
    res.version += 1
    res.updated_at=clock.now()
    _append_revision(session, res, "CANCEL", actor_user_id, clock.now())
    from app.modules.access.service import revoke_passes
    revoke_passes(res.id, conn=session.connection())
    _queue_change(session, clock, res, "CANCELLED")
    session.commit()
    return res


def restore(
    session: Session,
    clock: Clock,
    *,
    reservation_id: str,
    scope: dict,
    resolved_by: str,
    actor_user_id: str,
    expected_version: int,
) -> Reservation:
    res = _load_owned(session, clock, reservation_id=reservation_id, scope=scope, resolved_by=resolved_by)
    if res.service_date < service_date_of(clock.now()):
        raise ApiError(409, "RESERVATION_NOT_EDITABLE", "业务夜已结束。", {"reservation_id": res.id})
    from app.modules.returns.service import find_for_night
    if find_for_night(session.connection(), res.student_id, res.service_date):
        raise ApiError(409, "RETURN_EXISTS", "该业务夜已经返宿。", {})
    if res.status != "CANCELLED":
        raise ApiError(
            409,
            "RESERVATION_NOT_EDITABLE",
            "仅已取消的当夜预约可以恢复。",
            {"reservation_id": res.id, "status": res.status},
        )
    if res.version != expected_version:
        raise ApiError(
            409,
            "VERSION_CONFLICT",
            "预约已被更新，请重新获取最新版本。",
            {"expected_version": expected_version, "current_version": res.version},
        )
    res.status = "ACTIVE"
    res.version += 1
    res.updated_at=clock.now()
    _append_revision(session, res, "RESTORE", actor_user_id, clock.now())
    from app.modules.access.service import revoke_passes
    revoke_passes(res.id, conn=session.connection())
    _queue_change(session, clock, res, "APPROVED")
    session.commit()
    return res


def revisions(session: Session, clock: Clock, *, reservation_id: str, scope: dict, resolved_by: str) -> list[ReservationRevision]:
    res = _load_owned(session, clock, reservation_id=reservation_id, scope=scope, resolved_by=resolved_by)
    return list(
        session.scalars(
            select(ReservationRevision)
            .where(ReservationRevision.reservation_id == res.id)
            .order_by(ReservationRevision.version, ReservationRevision.changed_at)
        )
    )


def mark_fulfilled(session: Session, *, reservation_id: str, return_id: str) -> None:
    """供 B 的返宿模块在同一事务内调用：置 FULFILLED，不追加学生可见修订。

    返宿属于外部事实，证据链由 B 的 return_evidence 承载；本模块只保证状态与版本。
    M3 前 B 侧没有返宿聚合，本函数只定义边界，不接入任何 HTTP 入口。
    """
    res = session.get(Reservation, reservation_id, with_for_update=True)
    if res is None or res.status != "ACTIVE":
        raise ApiError(
            409,
            "RESERVATION_NOT_EDITABLE",
            "预约不处于可履行的状态。",
            {"reservation_id": reservation_id, "status": res.status if res else None},
        )
    res.status = "FULFILLED"
    res.version += 1
    session.flush()


def _queue_change(session: Session, clock: Clock, res: Reservation, kind: str) -> None:
    # 持久化 outbox 与预约同事务；通知失败由 worker 重试，不回滚已成功预约。
    from app.modules.notification.service import enqueue_reservation_event
    enqueue_reservation_event(session, clock, res, kind)


def list_for_building(building_id: str, service_date: date) -> list[dict]:
    from app.core.db import get_engine
    from app.modules.directory.service import list_building_residents
    anchor = summary_moment(service_date, ZoneInfo(get_settings().business_timezone))
    ids = [r["student_id"] for r in list_building_residents(building_id, anchor)]
    with Session(get_engine()) as session:
        rows = session.scalars(select(Reservation).where(Reservation.service_date == service_date, Reservation.student_id.in_(ids)).order_by(Reservation.id))
        return [{"student_id": r.student_id, "service_date": r.service_date.isoformat(), "planned_return_at": business_iso(r.planned_return_at), "status": r.status, "version": r.version, "updated_at": business_iso(r.updated_at)} for r in rows]


def fulfill_night(conn, student_id: str, service_date: date, return_id: str) -> None:
    """B 在正式返宿事务内调用；无预约补录也合法，历史 CLOSED 保留返宿事实。"""
    with Session(bind=conn) as session:
        res = session.scalar(select(Reservation).where(Reservation.student_id == student_id, Reservation.service_date == service_date).with_for_update())
        if res is not None and res.status in ("ACTIVE", "CLOSED"):
            res.status = "FULFILLED"
            res.version += 1
            session.flush()


def assert_pass_version(conn, reservation_id: str, version: int) -> None:
    with Session(bind=conn) as session:
        res = session.get(Reservation, reservation_id, with_for_update=True)
        if res is None or res.status != "ACTIVE" or res.version != version:
            raise ApiError(409, "PASS_REVOKED", "预约状态或版本已改变，请重新核验。", {"reservation_id": reservation_id})
        return {"student_id":res.student_id,"planned_return_at":res.planned_return_at,"service_date":res.service_date}


def list_for_building_at(building_id: str, service_date: date, at: datetime) -> list[dict]:
    from app.core.db import get_engine
    from app.modules.directory.service import list_building_residents
    ids=[r["student_id"] for r in list_building_residents(building_id,at)]
    with Session(get_engine()) as db:
        rows=db.scalars(select(Reservation).where(Reservation.service_date==service_date,Reservation.student_id.in_(ids)))
        out=[]
        for res in rows:
            rev=db.scalar(select(ReservationRevision).where(ReservationRevision.reservation_id==res.id,ReservationRevision.changed_at<=at).order_by(ReservationRevision.changed_at.desc(),ReservationRevision.version.desc()).limit(1))
            if rev is not None:
                out.append({"student_id":res.student_id,"service_date":service_date.isoformat(),"planned_return_at":business_iso(rev.planned_return_at),"status":rev.status,"version":rev.version,"updated_at":business_iso(rev.changed_at)})
        return out
