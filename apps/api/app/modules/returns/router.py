"""返宿记录接口（B 主责）：二维码使用情况读取与宿管人工补录。

写入只走 returns 的统一入口；补录按有效值班范围校验，前端隐藏入口不算权限（R11）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import SessionContext
from app.modules.returns import service

router = APIRouter(prefix="/return-records", tags=["returns"])

ReadDep = Annotated[SessionContext, Depends(require("return:read_scoped"))]
CreateDep = Annotated[SessionContext, Depends(require("manual_return:create"))]


@router.get("")
def list_records(
    guarded: ReadDep,
    request: Request,
    service_date: str | None = None,
    building_id: str | None = None,
) -> dict:
    """二维码使用情况：已签发 / 已核销 / 已过期 / 已撤销，加正式返宿记录。"""
    return service.usage_report(guarded, service_date, building_id, request.app.state.clock.now())


@router.post("/manual")
def manual_return(payload: dict, guarded: CreateDep, request: Request) -> dict:
    """宿管按门铃等实际返宿情况人工补录，与扫码共用同一条唯一约束。"""
    return service.manual_record(guarded, payload, request.app.state.clock.now())
