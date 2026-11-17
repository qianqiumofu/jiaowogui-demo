"""演示时钟接口（仅 Demo）：不真实等待即可跨越 23:30、00:00、06:00 边界。"""

from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.clock import service_date_of

router = APIRouter(prefix="/demo", tags=["demo"])


class ClockOffset(BaseModel):
    offset_minutes: int


def _clock(request: Request):
    return request.app.state.clock


def _state(clock) -> dict:
    now = clock.now()
    return {
        "now": now.isoformat(),
        # 业务夜由服务端判定，客户端只取用，不自行推算跨 06:00 的归属。
        "service_date": service_date_of(now).isoformat(),
        "offset_minutes": int(clock.offset.total_seconds() // 60),
    }


@router.get("/clock")
def get_clock(request: Request) -> dict:
    return _state(_clock(request))


@router.post("/clock")
def set_clock(payload: ClockOffset, request: Request) -> dict:
    clock = _clock(request)
    clock.offset = timedelta(minutes=payload.offset_minutes)
    return _state(clock)
