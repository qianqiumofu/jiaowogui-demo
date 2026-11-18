"""统计口径的唯一定义（M4 A 侧）。不需要数据库。

这块数字一旦两处各算一次就会分叉：日报周报说 3 人、园区统计说 4 人，答辩当场就会被问穿。
所以计数规则收在 `reports/summary.py`，`notification` 的逐夜计数已改为调用它，
本文件锁住口径本身，并验证投递正文用的确实是同一套数。
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.notification import service as notification_service
from app.modules.reports import summary

START = date(2026, 11, 16)
END = date(2026, 11, 18)


def fact(student: str, day: date, status: str) -> summary.ReservationFact:
    return summary.ReservationFact(student_id=student, service_date=day, status=status)


def test_cancelled_nights_are_not_counted_at_all() -> None:
    rows = [fact("stu_a", START, "CANCELLED")]
    night = summary.summarize_night(rows, service_date=START)
    assert (night.total, night.unconfirmed) == (0, 0)
    assert summary.distinct_students(rows) == 0 and summary.distinct_nights(rows) == 0


def test_unconfirmed_means_no_matching_record_not_guilty() -> None:
    """ACTIVE（夜还没过完）与 CLOSED（夜已过但没匹配到记录）都算未确认；FULFILLED 才算确认。"""
    rows = [
        fact("stu_a", START, "ACTIVE"),
        fact("stu_b", START, "CLOSED"),
        fact("stu_c", START, "FULFILLED"),
    ]
    night = summary.summarize_night(rows, service_date=START)
    assert (night.total, night.unconfirmed) == (3, 2)


def test_one_student_one_count_per_night() -> None:
    """数据库有唯一约束，口径也不靠它兜底：同夜同人重复出现只算一次。"""
    rows = [fact("stu_a", START, "ACTIVE"), fact("stu_a", START, "CLOSED")]
    assert summary.summarize_night(rows, service_date=START).total == 1


def test_students_and_nights_counted_separately() -> None:
    rows = [
        fact("stu_a", START, "ACTIVE"),
        fact("stu_a", END, "FULFILLED"),
        fact("stu_b", END, "CANCELLED"),
    ]
    assert summary.distinct_students(rows) == 1
    assert summary.distinct_nights(rows) == 2


def test_range_covers_empty_nights_in_order() -> None:
    nights = summary.summarize_range([fact("stu_a", END, "ACTIVE")], start=START, end=END)
    assert [night.service_date for night in nights] == [START, START + (END - START) // 2, END]
    assert [night.total for night in nights] == [0, 0, 1]


def test_range_rejects_reversed_window() -> None:
    with pytest.raises(ValueError):
        summary.summarize_range([], start=END, end=START)


def test_weekly_dispatch_uses_the_same_numbers() -> None:
    """投递正文用的逐夜计数必须等于口径模块的结果，防止两处再各写一遍。"""
    rows = [
        SimpleNamespace(student_id="stu_a", service_date=START, status="ACTIVE"),
        SimpleNamespace(student_id="stu_b", service_date=START, status="CANCELLED"),
        SimpleNamespace(student_id="stu_c", service_date=END, status="CLOSED"),
    ]
    counts = notification_service._night_counts(rows, week_start=START, service_date=END)
    expected = summary.summarize_range(
        [summary.ReservationFact(r.student_id, r.service_date, r.status) for r in rows],
        start=START,
        end=END,
    )

    assert [(c.service_date, c.total, c.unconfirmed) for c in counts] == [
        (n.service_date, n.total, n.unconfirmed) for n in expected
    ]
    assert [c.total for c in counts] == [1, 0, 1]
