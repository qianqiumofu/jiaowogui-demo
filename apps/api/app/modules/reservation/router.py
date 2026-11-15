"""预约模块占位（A 主责，M2 填充）。当夜唯一、全部通过、无限改期。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require
from app.modules.identity.dependencies import ContextDep

router = APIRouter(prefix="/reservations", tags=["reservation"])

CreateDep = Annotated[object, Depends(require("reservation:create"))]


@router.get("")
def list_reservations(context: ContextDep, service_date: str | None = None) -> dict:
    """返回 {"items": [...], "next_cursor": null}；M2 前为空。"""
    return {"items": [], "next_cursor": None}


@router.post("")
def create_reservation(payload: dict, guarded: CreateDep) -> dict:
    raise not_implemented("M2", "创建当日晚归预约")
