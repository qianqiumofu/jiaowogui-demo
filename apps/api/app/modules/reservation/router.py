"""预约 HTTP 入口（A 主责）。鉴权用 require(action)，数据范围交给 service 判定。"""

from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import Role, SessionContext
from app.modules.reservation import service
from app.modules.reservation.schemas import ReservationCreate, ReservationPatch, VersionedAction

router = APIRouter(prefix="/reservations", tags=["reservation"])

CreateDep = Annotated[SessionContext, Depends(require("reservation:create"))]
UpdateDep = Annotated[SessionContext, Depends(require("reservation:update"))]
CancelDep = Annotated[SessionContext, Depends(require("reservation:cancel"))]
RestoreDep = Annotated[SessionContext, Depends(require("reservation:restore"))]
ReadDep = Annotated[SessionContext, Depends(require("reservation:read"))]
SessionDep = Annotated[Session, Depends(get_session)]


def _moment(value: datetime) -> str:
    """同一条时刻在各接口上必须显示成同一个偏移：数据库回读是 UTC，入参带业务时区。"""
    tz = ZoneInfo(get_settings().business_timezone)
    return (value if value.tzinfo else value.replace(tzinfo=tz)).astimezone(tz).isoformat()


def _reservation(res) -> dict:
    return {
        "id": res.id,
        "student_id": res.student_id,
        "service_date": res.service_date.isoformat(),
        "status": res.status,
        "planned_return_at": _moment(res.planned_return_at),
        "reason": res.reason,
        "version": res.version,
        "created_at": _moment(res.created_at),
        "updated_at": _moment(res.updated_at),
    }


def _revision(rev) -> dict:
    return {
        "id": rev.id,
        "reservation_id": rev.reservation_id,
        "version": rev.version,
        "source": rev.source,
        "status": rev.status,
        "planned_return_at": _moment(rev.planned_return_at),
        "reason": rev.reason,
        "changed_by": rev.changed_by,
        "changed_at": _moment(rev.changed_at),
    }


def _scope_of(context: SessionContext) -> dict:
    return {k: v for k, v in dict(context.scope).items() if k != "resolved_by"}


@router.get("")
def list_reservations(
    request: Request,
    guarded: ReadDep,
    db: SessionDep,
    service_date: date | None = None,
) -> dict:
    items = service.list_reservations(
        db,
        request.app.state.clock,
        scope=dict(guarded.scope),
        service_date=service_date,
    )
    return {"items": [_reservation(r) for r in items], "next_cursor": None}


@router.get("/tonight")
def get_tonight(request: Request, guarded: ReadDep, db: SessionDep):
    student_id = guarded.scope.get("student_id")
    if guarded.active_role is not Role.STUDENT or not student_id:
        raise ApiError(
            403,
            "FORBIDDEN_ACTION",
            "tonight 视图仅面向学生本人。",
            {"action": "reservation:read", "role": guarded.active_role.value},
        )
    res = service.tonight(db, request.app.state.clock, student_id=student_id)
    return _reservation(res) if res is not None else None


@router.post("", status_code=201)
def create_reservation(request: Request, guarded: CreateDep, db: SessionDep, payload: ReservationCreate) -> dict:
    res = service.create_reservation(
        db,
        request.app.state.clock,
        student_id=guarded.scope["student_id"],
        school_id=guarded.school_id,
        actor_user_id=guarded.user_id,
        planned_return_at=payload.planned_return_at,
        reason=payload.reason,
    )
    return _reservation(res)


@router.patch("/{reservation_id}")
def patch_reservation(
    reservation_id: str, request: Request, guarded: UpdateDep, db: SessionDep, payload: ReservationPatch
) -> dict:
    res = service.reschedule(
        db,
        request.app.state.clock,
        reservation_id=reservation_id,
        scope=_scope_of(guarded),
        resolved_by=str(dict(guarded.scope).get("resolved_by", "")),
        actor_user_id=guarded.user_id,
        expected_version=payload.expected_version,
        planned_return_at=payload.planned_return_at,
        reason=payload.reason,
    )
    return _reservation(res)


@router.post("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: str, request: Request, guarded: CancelDep, db: SessionDep, payload: VersionedAction
) -> dict:
    res = service.cancel(
        db,
        request.app.state.clock,
        reservation_id=reservation_id,
        scope=_scope_of(guarded),
        resolved_by=str(dict(guarded.scope).get("resolved_by", "")),
        actor_user_id=guarded.user_id,
        expected_version=payload.expected_version,
    )
    return _reservation(res)


@router.post("/{reservation_id}/restore")
def restore_reservation(
    reservation_id: str, request: Request, guarded: RestoreDep, db: SessionDep, payload: VersionedAction
) -> dict:
    res = service.restore(
        db,
        request.app.state.clock,
        reservation_id=reservation_id,
        scope=_scope_of(guarded),
        resolved_by=str(dict(guarded.scope).get("resolved_by", "")),
        actor_user_id=guarded.user_id,
        expected_version=payload.expected_version,
    )
    return _reservation(res)


@router.get("/{reservation_id}/revisions")
def list_revisions(
    reservation_id: str, request: Request, guarded: ReadDep, db: SessionDep
) -> dict:
    revs = service.revisions(
        db,
        request.app.state.clock,
        reservation_id=reservation_id,
        scope=_scope_of(guarded),
        resolved_by=str(dict(guarded.scope).get("resolved_by", "")),
    )
    return {"items": [_revision(r) for r in revs], "next_cursor": None}
