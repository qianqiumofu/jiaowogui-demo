"""可推进的演示时钟：业务判定只允许使用服务端时间。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings

NIGHT_GATE_START_MINUTE = 0
NIGHT_GATE_END_MINUTE = 6 * 60
DEFAULT_SUMMARY_AT = "24:00"


def service_date_of(moment: datetime) -> date:
    """业务日 D = [D 06:00, D+1 06:00)，因此 06:00 前仍属前一日。"""
    if moment.tzinfo is None:
        raise ValueError("service_date_of 需要带时区时间")
    return (moment - timedelta(hours=6)).date()


def is_night_gate(moment: datetime) -> bool:
    """夜间门禁时段 [00:00, 06:00)。"""
    minutes = moment.hour * 60 + moment.minute
    return NIGHT_GATE_START_MINUTE <= minutes < NIGHT_GATE_END_MINUTE


def summary_moment(
    service_day: date, tz: ZoneInfo, value: str | None = None
) -> datetime:
    """业务夜 D 的名单汇总时刻，以 D 为基准：`23:30` 是 D 23:30，`24:00` 是 D+1 00:00。

    默认 24:00 与门禁时段起点重合，同时是业务夜 D 的首次申请截止时刻（R12）。
    """
    raw = value or get_settings().dorm_summary_at or DEFAULT_SUMMARY_AT
    hour_text, _, minute_text = raw.strip().partition(":")
    hour, minute = int(hour_text), int(minute_text)
    if (hour, minute) == (24, 0):
        return datetime.combine(service_day + timedelta(days=1), time(0, 0), tzinfo=tz)
    return datetime.combine(service_day, time(hour, minute), tzinfo=tz)


def is_summary_passed(moment: datetime, service_day: date | None = None) -> bool:
    """业务夜 `service_day` 的汇总时刻是否已过；不传则按 `moment` 所属业务夜判定。

    申请入口必须把**预约所属业务夜**传进来：截止跟着那一夜走，不跟着墙上钟一刀切。
    因此 00:30 提交当夜（service_day=昨天）已被关闭，提交次夜（service_day=今天）仍然放行。
    """
    day = service_day if service_day is not None else service_date_of(moment)
    return moment >= summary_moment(day, moment.tzinfo)


class Clock:
    def __init__(self, tz_name: str) -> None:
        self.tz = ZoneInfo(tz_name)

    def now(self) -> datetime:
        return datetime.now(self.tz)


class OffsetClock(Clock):
    """演示时钟：整体平移当前时间，用于跨越 24:00、00:00、06:00 边界。"""

    def __init__(self, tz_name: str, offset: timedelta = timedelta()) -> None:
        super().__init__(tz_name)
        self.offset = offset

    def now(self) -> datetime:
        return datetime.now(self.tz) + self.offset


def build_clock() -> Clock:
    return OffsetClock(get_settings().business_timezone)
