"""核验窗口与二维码时长的唯一判定处（A 主责，基线 R08、R09 与「统一日期与边界」）。

纯计算：只吃预约事实与时刻，不碰数据库、不写会话。B 的签码与门禁终端读同一批
枚举口径，不自行重算窗口或码寿命；客户端只显示这里给出的结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from app.core.clock import business_iso
from app.core.config import get_settings
from app.modules.reservation.service import night_bounds


class VerificationState(str, Enum):
    """现场核验窗口相对当前时刻的位置（R08，端点包含）。"""

    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    ENDED = "ENDED"


class PassState(str, Enum):
    """一张已签发二维码在当前时刻能否用于夜间通行。"""

    ALLOWED = "ALLOWED"
    CODE_EXPIRED = "CODE_EXPIRED"
    NIGHT_NOT_STARTED = "NIGHT_NOT_STARTED"
    NIGHT_ACCESS_ENDED = "NIGHT_ACCESS_ENDED"


def to_business(moment: datetime) -> datetime:
    """与 business_iso 同口径：无时区按业务时区解释，有则换算。"""
    tz = ZoneInfo(get_settings().business_timezone)
    return moment if moment.tzinfo else moment.replace(tzinfo=tz)


@dataclass(frozen=True)
class VerificationWindow:
    planned_return_at: datetime
    opens_at: datetime
    closes_at: datetime

    def contains(self, moment: datetime) -> bool:
        # 「前后 30 分钟，端点包含」（R08）：首尾两刻都算窗口内。
        return self.opens_at <= moment <= self.closes_at

    def state_at(self, moment: datetime) -> VerificationState:
        if moment < self.opens_at:
            return VerificationState.NOT_OPEN
        if moment > self.closes_at:
            return VerificationState.ENDED
        return VerificationState.OPEN


def margin_minutes() -> int:
    return get_settings().verification_margin_minutes


def code_seconds() -> int:
    return get_settings().pass_code_seconds


def window_of(planned_return_at: datetime) -> VerificationWindow:
    margin = timedelta(minutes=margin_minutes())
    planned = to_business(planned_return_at)
    return VerificationWindow(planned, planned - margin, planned + margin)


def state_of(planned_return_at: datetime, *, now: datetime) -> VerificationState:
    return window_of(planned_return_at).state_at(to_business(now))


def code_expires_at(issued_at: datetime) -> datetime:
    return to_business(issued_at) + timedelta(seconds=code_seconds())


def is_code_live(issued_at: datetime, *, now: datetime) -> bool:
    """完整 300 秒：第 299 秒仍可用，第 300 秒即失效（R09、docs/11）。"""
    return to_business(now) < code_expires_at(issued_at)


def pass_state(*, service_date: date, issued_at: datetime, now: datetime) -> PassState:
    """二维码可否用于今夜通行。窗口上界可被 06:00 截断，与核验窗口是否已过无关。"""
    moment = to_business(now)
    start, end = night_bounds(service_date, moment.tzinfo)
    # 06:00 之后旧码即使还在 300 秒内也算夜间授权结束，转学校正常通行流程（基线「统一日期与边界」）。
    if moment >= end:
        return PassState.NIGHT_ACCESS_ENDED
    if not is_code_live(issued_at, now=moment):
        return PassState.CODE_EXPIRED
    if moment < start:
        return PassState.NIGHT_NOT_STARTED
    return PassState.ALLOWED


def reservation_view(planned_return_at: datetime, *, service_date: date, now: datetime) -> dict:
    """预约响应里的核验时段视图；判定全在服务端，客户端只显示。"""
    moment = to_business(now)
    window = window_of(planned_return_at)
    _, night_end = night_bounds(service_date, moment.tzinfo)
    return {
        "opens_at": business_iso(window.opens_at),
        "closes_at": business_iso(window.closes_at),
        "state": window.state_at(moment).value,
        "margin_minutes": margin_minutes(),
        "code_seconds": code_seconds(),
        "night_access_ends_at": business_iso(night_end),
    }
