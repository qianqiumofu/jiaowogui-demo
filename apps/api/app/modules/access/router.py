"""通行与门禁模块占位（B 主责，M3 填充）：签码、撤销、核销、回执与对账。

模拟终端使用设备身份而非学生会话；设备令牌校验在此模块实现。
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/device", tags=["access"])


@router.post("/scan")
def scan(payload: dict) -> dict:
    raise not_implemented("M3", "扫码核销与原子归返占用")
