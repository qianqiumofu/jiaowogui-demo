"""演示时钟接口（仅 Demo）：不真实等待即可跨越 23:30、00:00、06:00 边界。"""

from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.clock import service_date_of
from app.modules.reservation.service import night_bounds

router = APIRouter(prefix="/demo", tags=["demo"])


class ClockOffset(BaseModel):
    offset_minutes: int


def _clock(request: Request):
    return request.app.state.clock


def _state(clock) -> dict:
    now = clock.now()
    service_date = service_date_of(now)
    start, end = night_bounds(service_date, now.tzinfo)
    return {
        "now": now.isoformat(),
        # 业务夜与门禁时段都由服务端判定，客户端只取用来列举可选时刻。
        "service_date": service_date.isoformat(),
        "night_window": [start.isoformat(), end.isoformat()],
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
