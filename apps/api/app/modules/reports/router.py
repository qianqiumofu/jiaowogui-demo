"""报告模块占位（A 主责，M4 填充）：日报次日 08:30、周报周一 09:00。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require

router = APIRouter(prefix="/reports", tags=["reports"])

ReadDep = Annotated[object, Depends(require("report:read"))]


@router.get("/daily")
def daily(guarded: ReadDep) -> dict:
    raise not_implemented("M4", "辅导员日报")
