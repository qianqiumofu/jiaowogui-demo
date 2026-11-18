"""日报／周报取数与视图（M4 A 侧第二块）。不需要数据库。

这块一旦与投递正文分叉，答辩时会被同一个学生的两个数字问穿，所以：
- 视图是纯函数，样例文件直接由它渲染，改了实现忘了改样例会当场红；
- 契约的必填集、模板常量与样例结构必须一致；
- 「前一晚」「未来日期」「周报窗口」这些边界都在服务端判定，客户端不参与。
"""

import json
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.core.clock import service_date_of
from app.core.config import get_settings
from app.core.errors import ApiError
from app.modules.reports import readmodel, summary

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "contracts" / "examples"
TZ = ZoneInfo("Asia/Shanghai")
# 业务夜 2026-11-15：门禁时段 11-16 00:00—06:00，日报在次日上午生成。
NIGHT = date(2026, 11, 15)
DAILY_NOW = datetime(2026, 11, 16, 8, 30, tzinfo=TZ)
WEEKLY_NOW = datetime(2026, 11, 16, 9, 0, tzinfo=TZ)

REMINDER_WORDS = ("提醒", "催办", "超时", "未归", "升级")


@pytest.fixture(autouse=True)
def pinned_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """样例锁死在演示默认口径上，本机 .env 改了阈值不该让样例测试忽红忽绿。"""
    monkeypatch.setenv("WEEKLY_REPORT_NIGHTS", "7")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def res(student: str, night: date, hour: int, minute: int, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        student_id=student,
        service_date=night,
        status=status,
        planned_return_at=datetime.combine(night + timedelta(days=1), time(hour, minute), TZ),
    )


def daily_items() -> list[SimpleNamespace]:
    return [
        res("stu_synth_0003", NIGHT, 2, 5, "CANCELLED"),
        res("stu_synth_0002", NIGHT, 1, 10, "ACTIVE"),
        res("stu_synth_0001", NIGHT, 0, 40, "FULFILLED"),
    ]


def week_items() -> list[SimpleNamespace]:
    return [
        res("stu_synth_0002", date(2026, 11, 11), 1, 40, "ACTIVE"),
        res("stu_synth_0001", date(2026, 11, 11), 0, 25, "FULFILLED"),
        res("stu_synth_0001", date(2026, 11, 13), 2, 15, "CLOSED"),
        *daily_items(),
    ]


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_daily_view_output_is_what_the_example_shows() -> None:
    body = readmodel.daily_view(daily_items(), service_date=NIGHT, now=DAILY_NOW)
    assert body == example("report-daily-success.json")


def test_weekly_view_matches_the_example() -> None:
    start, end = readmodel.week_window(NIGHT)
    body = readmodel.weekly_view(week_items(), start=start, end=end, now=WEEKLY_NOW)
    assert body == example("report-weekly-success.json")


def test_cancelled_night_shows_in_rows_but_not_in_counts() -> None:
    body = readmodel.daily_view(daily_items(), service_date=NIGHT, now=DAILY_NOW)
    assert [item["status"] for item in body["items"]] == ["FULFILLED", "ACTIVE", "CANCELLED"]
    assert body["totals"] == {"students": 2, "nights": 1, "unconfirmed": 1}


def test_rows_are_ordered_by_planned_time_then_student() -> None:
    rows = readmodel.daily_view(daily_items(), service_date=NIGHT, now=DAILY_NOW)["items"]
    assert [row["planned_return_at"] for row in rows] == sorted(row["planned_return_at"] for row in rows)


def test_weekly_window_keeps_empty_nights_and_dedupes_students() -> None:
    body = readmodel.weekly_view(week_items(), start=date(2026, 11, 9), end=NIGHT, now=WEEKLY_NOW)
    assert body["nights_covered"] == 7
    assert [night["total"] for night in body["nights"]] == [0, 0, 2, 0, 1, 0, 2]
    assert body["totals"]["students"] == 2
    assert body["totals"]["unconfirmed"] == sum(night["unconfirmed"] for night in body["nights"])


def test_week_window_length_is_read_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEEKLY_REPORT_NIGHTS", "3")
    get_settings.cache_clear()
    assert readmodel.week_window(NIGHT) == (date(2026, 11, 13), NIGHT)


def test_default_report_night_is_the_finished_one() -> None:
    # 05:59 仍属 11-15 这一夜，所以「前一晚」是 11-14；06:01 业务日翻页，前一晚才变成 11-15。
    assert readmodel.previous_night(datetime(2026, 11, 16, 5, 59, tzinfo=TZ)) == date(2026, 11, 14)
    assert readmodel.previous_night(datetime(2026, 11, 16, 6, 1, tzinfo=TZ)) == date(2026, 11, 15)


def test_dates_after_the_current_night_are_refused() -> None:
    latest = service_date_of(DAILY_NOW)
    assert readmodel.resolve_service_date(latest, now=DAILY_NOW) == latest
    assert readmodel.resolve_service_date(None, now=DAILY_NOW) == latest - timedelta(days=1)
    with pytest.raises(ApiError) as caught:
        readmodel.resolve_service_date(latest + timedelta(days=1), now=DAILY_NOW)
    assert caught.value.status_code == 422
    assert caught.value.code == "VALIDATION_FAILED"


def test_caliber_wording_comes_from_the_same_place_as_the_counts() -> None:
    body = readmodel.daily_view(daily_items(), service_date=NIGHT, now=DAILY_NOW)
    assert body["caliber_notes"] == [summary.CANCELLED_NOTE, summary.UNCONFIRMED_NOTE]
    assert readmodel.UNCONFIRMED_NOTE is summary.UNCONFIRMED_NOTE


def test_report_text_never_reminds_or_judges_unreturned() -> None:
    """R15 的口径句本身含「提醒／催办」字样，扫描前先剔除。"""
    for name in ("report-daily-success.json", "report-weekly-success.json"):
        scanned = json.dumps(example(name), ensure_ascii=False).replace(summary.UNCONFIRMED_NOTE, "")
        assert not [word for word in REMINDER_WORDS if word in scanned], name


def test_contract_requires_exactly_what_the_views_return() -> None:
    spec = yaml.safe_load((REPO_ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]

    daily = readmodel.daily_view(daily_items(), service_date=NIGHT, now=DAILY_NOW)
    weekly = readmodel.weekly_view(week_items(), start=date(2026, 11, 9), end=NIGHT, now=WEEKLY_NOW)
    assert set(schemas["DailyReport"]["required"]) == set(daily)
    assert set(schemas["WeeklyReport"]["required"]) == set(weekly)
    assert schemas["DailyReport"]["properties"]["template"]["const"] == daily["template"]
    assert schemas["WeeklyReport"]["properties"]["template"]["const"] == weekly["template"]

    for name, body in (
        ("report-daily-success.json", daily),
        ("report-weekly-success.json", weekly),
    ):
        assert set(example(name)) == set(body), name
    assert set(example("report-daily-success.json")["items"][0]) == set(
        schemas["ReportItem"]["required"]
    )
    assert set(example("report-weekly-success.json")["nights"][0]) == set(
        schemas["ReportNight"]["required"]
    )

    for path in ("/reports/daily", "/reports/weekly"):
        params = spec["paths"][path]["get"]["parameters"]
        assert params[0]["$ref"] == "#/components/parameters/ServiceDate"
