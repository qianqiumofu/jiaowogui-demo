"""申请时弹窗（M4 A 侧第一块）：预约创建响应带出的规则事实。全部需要真实 PostgreSQL。

覆盖四件事：
- 弹窗时机：连续第三夜创建时才出现，第四夜不重复弹（一晚最多一次，无需额外存储）。
- 取消的夜晚不计晚归夜数（基线「取消、领码、未确认不计实际晚归」）。
- 弹窗是纯提示：不改变自动通过（R06）、不进改期响应、也不产生任何通知任务（R15）。
- 学生读不到风险事件入口：弹窗不等于开放 `/risk-events`。
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import service_date_of
from app.core.config import get_settings
from tests.conftest import API, auth, token_for

TZ = ZoneInfo("Asia/Shanghai")

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture()
def campus_token(client: TestClient) -> str:
    return token_for(client, "campus")


def now_bj() -> datetime:
    return datetime(2026,11,15,18,0,tzinfo=TZ)


def offset_clock(client: TestClient, target: datetime) -> None:
    minutes = int((target - datetime.now(TZ)).total_seconds() // 60)
    response = client.post(f"{API}/demo/clock", json={"offset_minutes": minutes})
    assert response.status_code == 200, response.text


def at_night(night_index: int) -> datetime:
    """把演示时钟推进到第 night_index 个业务夜的 18:00（稳在业务夜内）。"""
    day = service_date_of(now_bj()) + timedelta(days=night_index)
    return datetime.combine(day, time(18, 0), TZ)


def create_on(client: TestClient, token: str, night_index: int) -> dict:
    offset_clock(client, at_night(night_index))
    planned = at_night(night_index) + timedelta(hours=7, minutes=30)  # 次日 01:30
    response = client.post(
        f"{API}/reservations",
        json={"planned_return_at": planned.isoformat(), "reason": "赶项目进度"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_notice_appears_on_third_night_only(client, student_token) -> None:
    first = create_on(client, student_token, 0)
    assert "risk_notice" not in first
    second = create_on(client, student_token, 1)
    assert "risk_notice" not in second

    third = create_on(client, student_token, 2)
    notice = third["risk_notice"]
    assert notice["rule_version"] == get_settings().risk_rule_version
    assert notice["triggered_by"] == "TIMES"
    assert notice["times"] == 3 and notice["consecutive_nights"] == 3
    assert notice["window_nights"] == 7
    # 服务端正文，客户端不拼接；口径与「演示配置」两句都必须在。
    assert "预约晚归" in notice["message"] and "演示配置" in notice["message"]
    assert notice["nights"] == sorted(notice["nights"]) and len(notice["nights"]) == 3
    assert notice["nights"][-1] == third["service_date"]

    # 第四夜：当夜之前已越界，不再重复弹。
    fourth = create_on(client, student_token, 3)
    assert "risk_notice" not in fourth
    assert fourth["status"] == "ACTIVE"


def test_cancelled_night_does_not_count(client, student_token) -> None:
    create_on(client, student_token, 0)
    second = create_on(client, student_token, 1)
    cancelled = client.post(
        f"{API}/reservations/{second['id']}/cancel",
        json={"expected_version": second["version"]}, headers=auth(student_token))
    assert cancelled.status_code == 200, cancelled.text
    third = create_on(client, student_token, 2)
    assert "risk_notice" not in third
    fourth = create_on(client, student_token, 3)
    assert fourth["risk_notice"]["times"] == 3
    assert fourth["risk_notice"]["consecutive_nights"] == 2


def test_popup_creates_no_notification_job(client, student_token, campus_token) -> None:
    """R15：弹窗只是查询派生的提示，不许留下任何投递任务。"""
    for index in range(3):
        create_on(client, student_token, index)
    jobs = client.get(f"{API}/notification-jobs", headers=auth(campus_token))
    assert jobs.status_code == 200, jobs.text
    assert [j["template"] for j in jobs.json()["items"]] == ["DORM_APPROVED"] * 3
    assert all(j["business_key"].endswith(":APPROVED") for j in jobs.json()["items"])
    assert client.get(f"{API}/notifications", headers=auth(student_token)).status_code == 403


def test_reschedule_never_carries_notice(client, student_token) -> None:
    create_on(client, student_token, 0)
    create_on(client, student_token, 1)
    third = create_on(client, student_token, 2)
    assert "risk_notice" in third

    later = (at_night(2) + timedelta(hours=8)).isoformat()  # 次日 02:00
    patched = client.patch(
        f"{API}/reservations/{third['id']}",
        json={"expected_version": third["version"], "planned_return_at": later},
        headers=auth(student_token),
    )
    assert patched.status_code == 200, patched.text
    assert "risk_notice" not in patched.json()
    assert patched.json()["version"] == third["version"] + 1


def test_student_still_cannot_read_risk_events(client, student_token) -> None:
    """弹窗不放宽权限：学生端没有风险事件入口。"""
    for index in range(3):
        create_on(client, student_token, index)
    response = client.get(f"{API}/risk-events", headers=auth(student_token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"
