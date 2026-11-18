"""规则引擎（A 主责）：只做纯计算，不查库、不读时钟、不写措辞。

口径是「预约晚归的业务夜数与连续性」，不是实际晚归：实际返宿要 B 的记录模块，
落地前不改口径（基线「报告、风险和权限默认」）。这里也不看是否确认返宿，
超时与未确认一律不构成触发事实（R15）。

阈值全部来自配置，未确认的取值不得写死在分支里（R16）；`version` 与阈值同批变更，
弹窗和提示正文都带它，便于事后说明「当时按哪一版算的」。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.config import get_settings

TIMES = "TIMES"
CONSECUTIVE = "CONSECUTIVE"


@dataclass(frozen=True)
class RuleSet:
    version: str
    window_nights: int
    times_threshold: int
    consecutive_threshold: int


def current_rule_set() -> RuleSet:
    settings = get_settings()
    return RuleSet(
        version=settings.risk_rule_version,
        window_nights=settings.risk_window_nights,
        times_threshold=settings.risk_times_threshold,
        consecutive_threshold=settings.risk_consecutive_threshold,
    )


@dataclass(frozen=True)
class Evaluation:
    rule_version: str
    window_nights: int
    nights: tuple[date, ...]
    times: int
    consecutive_nights: int
    crossed_by: str | None
    #: 窗口内去掉当夜后不再越界，即「本夜预约使口径越界」。
    first_crossing: bool

    @property
    def crossed(self) -> bool:
        return self.crossed_by is not None


def longest_run(nights: Iterable[date]) -> int:
    """连续业务夜的最大长度；空集合为 0。"""
    days = sorted(set(nights))
    if not days:
        return 0
    best = run = 1
    for previous, current in zip(days, days[1:]):
        run = run + 1 if (current - previous).days == 1 else 1
        best = max(best, run)
    return best


def _crossed_by(times: int, consecutive: int, rules: RuleSet) -> str | None:
    # 两者同时越界时取 TIMES：次数是更长期的事实，文案先说它。
    if times >= rules.times_threshold:
        return TIMES
    if consecutive >= rules.consecutive_threshold:
        return CONSECUTIVE
    return None


def evaluate(nights: Iterable[date], *, tonight: date, rules: RuleSet) -> Evaluation:
    """统计 [tonight-window+1, tonight] 内的晚归业务夜；取消的夜晚由调用方剔除。"""
    start = tonight - timedelta(days=rules.window_nights - 1)
    in_window = tuple(sorted({day for day in nights if start <= day <= tonight}))
    crossed_by = _crossed_by(len(in_window), longest_run(in_window), rules)
    without_tonight = tuple(day for day in in_window if day != tonight)
    return Evaluation(
        rule_version=rules.version,
        window_nights=rules.window_nights,
        nights=in_window,
        times=len(in_window),
        consecutive_nights=longest_run(in_window),
        crossed_by=crossed_by,
        first_crossing=crossed_by is not None
        and _crossed_by(len(without_tonight), longest_run(without_tonight), rules) is None,
    )
