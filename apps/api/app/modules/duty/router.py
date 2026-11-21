"""值班模块（B 主责）：固定负责人靠「换人」维护，阿姨的额外楼栋靠「代班」按夜追加。

写入动作沿用基线已有的 `duty:assign`（固定名册）与 `duty:switch`（当夜代班），只授予园区；
宿管与辅导员调 `duty:read` 拿到的是强制收窄到本人的记录。值守范围由 `identity.resolve_scope`
经 `directory` 从「固定名册 ∪ 当夜代班」现算，这里只负责写入与撤销，不存在「全校授权」这种取值。
审计由领域服务在同一事务内落笔，router 不再单独开一次会话。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modules.authorization.dependencies import require
from app.modules.duty import service
from app.modules.identity.schemas import SessionContext

router = APIRouter(prefix="/duty-assignments", tags=["duty"])
roster_router = APIRouter(prefix="/duty-roster", tags=["duty"])

ReadDep = Annotated[SessionContext, Depends(require("duty:read"))]
AssignDep = Annotated[SessionContext, Depends(require("duty:assign"))]
SwitchDep = Annotated[SessionContext, Depends(require("duty:switch"))]


@roster_router.get("")
def list_duty_roster(
    guarded: ReadDep,
    request: Request,
    building_id: str | None = None,
    staff_user_id: str | None = None,
    park_org_id: str | None = None,
) -> dict:
    return service.list_roster(
        guarded,
        building_id=building_id,
        staff_user_id=staff_user_id,
        park_org_id=park_org_id,
        at=request.app.state.clock.now(),
    )


@roster_router.post("")
def set_duty_roster(payload: dict, guarded: AssignDep, request: Request) -> dict:
    """园区端登记/更换某栋楼的固定值班负责人，写入即对之后每一夜生效。"""
    return service.set_roster(
        payload, request.app.state.clock.now(), actor_user_id=guarded.user_id
    )


@roster_router.post("/revoke")
def revoke_duty_roster(payload: dict, guarded: AssignDep, request: Request) -> dict:
    return service.revoke_roster(
        payload, request.app.state.clock.now(), actor_user_id=guarded.user_id
    )


@router.get("")
def list_duty(
    guarded: ReadDep,
    request: Request,
    building_id: str | None = None,
    staff_user_id: str | None = None,
    service_date: str | None = None,
) -> dict:
    """按夜代班一览（固定负责人在 `GET /duty-roster`）。"""
    return service.list_duties(
        guarded,
        building_id=building_id,
        staff_user_id=staff_user_id,
        service_date=service_date,
        at=request.app.state.clock.now(),
    )


@router.post("", status_code=201)
def assign_duty(payload: dict, guarded: SwitchDep, request: Request) -> dict:
    """登记当夜代班：与 `/switch` 同一件事，保留这个入口给基线已有的调用方。"""
    return service.grant_substitute(
        payload, request.app.state.clock.now(), actor_user_id=guarded.user_id
    )


@router.post("/switch")
def switch_duty(payload: dict, guarded: SwitchDep, request: Request) -> dict:
    """园区端登记当夜代班：某一夜让某位阿姨在自己那栋之外再多管一栋。"""
    return service.grant_substitute(
        payload, request.app.state.clock.now(), actor_user_id=guarded.user_id
    )


@router.delete("/{duty_id}")
def revoke_duty_by_id(duty_id: str, guarded: AssignDep, request: Request) -> dict:
    """撤销代班：契约只开 DELETE 这一条口子，不做 POST /revoke 的第二种写法。"""
    return service.revoke(
        {"duty_id": duty_id}, request.app.state.clock.now(), actor_user_id=guarded.user_id
    )
