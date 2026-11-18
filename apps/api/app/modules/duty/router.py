"""代班模块占位（B 主责，M1 填充）。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require

router = APIRouter(prefix="/duty-assignments", tags=["duty"])

ReadDep = Annotated[object, Depends(require("duty:read"))]
SwitchDep = Annotated[object, Depends(require("duty:switch"))]


@router.get("")
def list_duty(guarded: ReadDep) -> dict:
    return {"items": [], "next_cursor": None}


@router.post("/switch")
def switch(payload: dict, guarded: SwitchDep) -> dict:
    raise not_implemented("M1", "跨楼栋代班生效与失效校验")
