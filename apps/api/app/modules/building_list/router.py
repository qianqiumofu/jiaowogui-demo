"""楼栋名单模块占位（B 主责，M2 填充）：仅有效值班楼栋可见。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require

router = APIRouter(prefix="/buildings", tags=["building-list"])

ReadDep = Annotated[object, Depends(require("building:tonight"))]


@router.get("/{building_id}/tonight")
def tonight(building_id: str, guarded: ReadDep) -> dict:
    raise not_implemented("M2", "当晚预约名单快照与实时更新")
