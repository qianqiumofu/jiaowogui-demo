"""风险模块占位（A 主责，M4 填充）。学生不可读；园区只查询、不收推送。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require

router = APIRouter(prefix="/risk-events", tags=["risk"])

ReadDep = Annotated[object, Depends(require("risk:read"))]
AckDep = Annotated[object, Depends(require("risk:ack"))]


@router.get("")
def list_events(guarded: ReadDep, status: str | None = None) -> dict:
    return {"items": [], "next_cursor": None}


@router.post("/{event_id}/ack")
def ack(event_id: str, guarded: AckDep) -> dict:
    raise not_implemented("M4", "风险事件确认与跟进（收件人限定辅导员与当班宿管）")
