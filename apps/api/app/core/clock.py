"""可推进的演示时钟：业务判定只允许使用服务端时间。"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import API_ROOT, get_settings

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


class SharedOffsetClock(Clock):
    """把偏移量存在共享文件里的演示时钟，API 与 worker 因此看到同一个「现在」。

    每次读取都回到文件取值，写入用临时文件替换，所以推进时钟不需要重启进程。
    文件缺失或内容不可用时按零偏移处理，不能因为演示状态文件坏掉而让判定失败。
    """

    def __init__(self, tz_name: str, state_file: Path) -> None:
        super().__init__(tz_name)
        self.state_file = state_file

    @property
    def offset(self) -> timedelta:
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return timedelta()
        minutes = raw.get("offset_minutes") if isinstance(raw, dict) else None
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool):
            return timedelta()
        return timedelta(minutes=float(minutes))

    @offset.setter
    def offset(self, value: timedelta) -> None:
        payload = json.dumps({"offset_minutes": value.total_seconds() / 60}, ensure_ascii=False)
        tmp = self.state_file.with_name(f"{self.state_file.name}.{os.getpid()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.state_file)

    def now(self) -> datetime:
        return datetime.now(self.tz) + self.offset


def _state_file(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else API_ROOT / path


def build_clock() -> Clock:
    settings = get_settings()
    if settings.demo_clock_file:
        return SharedOffsetClock(settings.business_timezone, _state_file(settings.demo_clock_file))
    return OffsetClock(settings.business_timezone)
