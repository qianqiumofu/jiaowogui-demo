"""可推进的演示时钟：业务判定只允许使用服务端时间。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings

NIGHT_GATE_START_MINUTE = 0
NIGHT_GATE_END_MINUTE = 6 * 60
SUMMARY_MINUTE = 23 * 60 + 30


def service_date_of(moment: datetime) -> date:
    """业务日 D = [D 06:00, D+1 06:00)，因此 06:00 前仍属前一日。"""
    if moment.tzinfo is None:
        raise ValueError("service_date_of 需要带时区时间")
    return (moment - timedelta(hours=6)).date()


def is_night_gate(moment: datetime) -> bool:
    """夜间门禁时段 [00:00, 06:00)。"""
    minutes = moment.hour * 60 + moment.minute
    return NIGHT_GATE_START_MINUTE <= minutes < NIGHT_GATE_END_MINUTE


def business_iso(moment: datetime) -> str:
    """把任意来源的时刻统一成业务时区偏移：数据库回读是 UTC，入参带业务时区。"""
    tz = ZoneInfo(get_settings().business_timezone)
    return (moment if moment.tzinfo else moment.replace(tzinfo=tz)).astimezone(tz).isoformat()


class Clock:
    def __init__(self, tz_name: str) -> None:
        self.tz = ZoneInfo(tz_name)

    def now(self) -> datetime:
        return datetime.now(self.tz)


class OffsetClock(Clock):
    """演示时钟：整体平移当前时间，用于跨越 23:30、00:00、06:00 边界。"""

    def __init__(self, tz_name: str, offset: timedelta = timedelta()) -> None:
        super().__init__(tz_name)
        self.offset = offset

    def now(self) -> datetime:
        return datetime.now(self.tz) + self.offset


def build_clock() -> Clock:
    return OffsetClock(get_settings().business_timezone)
