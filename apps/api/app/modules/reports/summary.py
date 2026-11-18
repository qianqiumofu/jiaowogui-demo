"""统计口径的唯一计算处（A 主责，M4 报告与 B 的园区统计共用）。

口径定义集中在这里，是为了让日报、周报、园区筛选与导出报出同一批数字：

- 一晚一条：一个（学生 × 业务夜）最多算一次，取消的预约不计入任何计数（R05、R06）。
- 人数按学号去重，夜数按业务夜去重；两者都不等于「实际晚归人数」——
  实际是否晚归以门禁通行记录为准，B 的 `returns` 落地前不得改口。
- 「未确认返宿」＝预约仍在 ACTIVE/CLOSED，只表示当晚没有匹配到通行记录，
  不代表已经证明未归，绝不据此生成提醒、催办或升级（R15）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

CANCELLED = "CANCELLED"
FULFILLED = "FULFILLED"
# ACTIVE＝业务夜还在进行中；CLOSED＝夜已过但始终没匹配到记录。两者都还没被确认。
UNCONFIRMED_STATUSES = ("ACTIVE", "CLOSED")

# 口径措辞和口径定义写在一起：投递正文与按需报告引同一句，不会出现一处改了另一处没改。
UNCONFIRMED_NOTE = "未确认返宿只表示当晚没有匹配到通行记录，不代表已经证明未归，系统不据此提醒、催办或升级。"
CANCELLED_NOTE = "取消的夜晚不计入任何统计。"


@dataclass(frozen=True)
class ReservationFact:
    """参与统计的最小预约事实；ORM 对象与测试构造体都能映射成它。"""

    student_id: str
    service_date: date
    status: str


def is_counted(fact: ReservationFact) -> bool:
    return fact.status != CANCELLED


def is_unconfirmed(fact: ReservationFact) -> bool:
    return fact.status in UNCONFIRMED_STATUSES


def counted_facts(facts: Iterable[ReservationFact]) -> list[ReservationFact]:
    return [fact for fact in facts if is_counted(fact)]


def distinct_students(facts: Iterable[ReservationFact]) -> int:
    return len({fact.student_id for fact in counted_facts(facts)})


def distinct_nights(facts: Iterable[ReservationFact]) -> int:
    return len({fact.service_date for fact in counted_facts(facts)})


@dataclass(frozen=True)
class NightSummary:
    service_date: date
    total: int
    unconfirmed: int


def summarize_night(facts: Iterable[ReservationFact], *, service_date: date) -> NightSummary:
    rows = [fact for fact in counted_facts(facts) if fact.service_date == service_date]
    return NightSummary(
        service_date=service_date,
        total=len({row.student_id for row in rows}),
        unconfirmed=len({row.student_id for row in rows if is_unconfirmed(row)}),
    )


def summarize_range(
    facts: Iterable[ReservationFact], *, start: date, end: date
) -> list[NightSummary]:
    """逐夜给出 `[start, end]` 的汇总，一个预约都没有的夜也占一行（total=0）。"""
    if end < start:
        raise ValueError("summarize_range 要求 end 不早于 start")
    rows = list(facts)
    return [
        summarize_night(rows, service_date=start + timedelta(days=offset))
        for offset in range((end - start).days + 1)
    ]
