"""演示时钟接口（仅 Demo）：不真实等待即可跨越 23:30、00:00、06:00 边界。"""

from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/demo", tags=["demo"])


class ClockOffset(BaseModel):
    offset_minutes: int


def _clock(request: Request):
    return request.app.state.clock


@router.get("/clock")
def get_clock(request: Request) -> dict:
    clock = _clock(request)
    return {"now": clock.now().isoformat(), "offset_minutes": int(clock.offset.total_seconds() // 60)}


@router.post("/clock")
def set_clock(payload: ClockOffset, request: Request) -> dict:
    clock = _clock(request)
    clock.offset = timedelta(minutes=payload.offset_minutes)
    return {"now": clock.now().isoformat(), "offset_minutes": payload.offset_minutes}
