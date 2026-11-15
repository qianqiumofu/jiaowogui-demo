"""返宿记录模块占位（B 主责，唯一写入方，M3 填充）。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require

router = APIRouter(prefix="/return-records", tags=["returns"])

ReadDep = Annotated[object, Depends(require("return:read_scoped"))]
CreateDep = Annotated[object, Depends(require("manual_return:create"))]


@router.get("")
def list_records(guarded: ReadDep, service_date: str | None = None) -> dict:
    return {"items": [], "next_cursor": None}


@router.post("/manual")
def manual_return(payload: dict, guarded: CreateDep) -> dict:
    raise not_implemented("M3", "宿管人工补录（统一 confirm_return 入口）")
