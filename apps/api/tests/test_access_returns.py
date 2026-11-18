"""通行核销与正式返宿记录：单次使用、300 秒有效期、夜间时段、门禁绑定与当夜唯一。

对应基线场景 2、3、7 与 R04、R08、R09、R10；并发与唯一约束连真实 PostgreSQL 验证。
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import get_engine
from app.core.errors import ApiError
from app.modules.access import service as access
from app.modules.returns import service as returns
from tests.conftest import API, auth, jump_clock, token_for

TZ = ZoneInfo("Asia/Shanghai")

# 演示凭据：库里只存摘要，明文按 docs/10 的合成约定派生，不是真实设备密钥。
DEVICE_TOKEN = {
    "dev_synth_a1_01": "dev_synth:dev_synth_a1_01",
    "dev_synth_a2_01": "dev_synth:dev_synth_a2_01",
}


def _grant(
    planned: datetime,
    student_id: str = "stu_synth_0001",
    building_id: str = "bldg_a1",
    gate_id: str | None = "gate_a1_north",
) -> dict:
    return {
        "student_id": student_id,
        "building_id": building_id,
        "verification_id": "vs_synth_test_0001",
        "planned_return_at": planned.isoformat(),
        "window_start": (planned - timedelta(minutes=30)).isoformat(),
        "window_end": (planned + timedelta(minutes=30)).isoformat(),
        "verified_at": planned.isoformat(),
        "gate_id": gate_id,
    }


def _issue(client: TestClient, when: datetime, **changes) -> dict:
    student_id = changes.get("student_id", "stu_synth_0001")
    building_id = changes.get("building_id", "bldg_a1")
    planned = changes.get("planned", when)
    grant = _grant(planned, student_id, building_id, changes.get("gate_id", "gate_a1_north"))
    return access.issue_pass(changes.get("reservation_id", "rsv_synth_test_0001"), 1, grant)


def _scan(client: TestClient, issued: dict, when: datetime, device: str = "dev_synth_a1_01"):
    return access.consume(device, DEVICE_TOKEN[device], issued["token"], when)


def _count(sql: str, params: dict) -> int:
    with get_engine().connect() as conn:
        return int(conn.execute(text(sql), params).scalar() or 0)


def _purge(reservation_id: str, student_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM return_records WHERE student_id = :s"), {"s": student_id}
        )
        conn.execute(
            text("DELETE FROM pass_codes WHERE reservation_id = :r"), {"r": reservation_id}
        )


# 用例断言的是「按学生/按夜」的条数，而演示服务与测试共用同一个库：
# 先清一遍自己用到的合成学生，跑测试才不会把演示数据算进来。
@pytest.fixture(autouse=True)
def _clean_demo_rows() -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM return_records WHERE student_id = ANY(:students)"
            ),
            {"students": ["stu_synth_0001", "stu_synth_0002", "stu_synth_0003", "stu_synth_0004"]},
        )
        conn.execute(
            text("DELETE FROM pass_codes WHERE student_id = ANY(:students)"),
            {"students": ["stu_synth_0001", "stu_synth_0002", "stu_synth_0003", "stu_synth_0004"]},
        )


def test_a_successful_scan_is_the_only_way_to_make_the_formal_record(client) -> None:
    when = jump_clock(client, 0, 40)
    issued = _issue(client, when)
    try:
        result = _scan(client, issued, when)
        assert result["attempt_status"] == "SUCCEEDED"
        assert result["duplicate"] is False
        assert result["return_id"].startswith("ret_")
        assert result["building_id"] == "bldg_a1"
        assert result["gate_id"] == "gate_a1_north"
        assert _count(
            "SELECT count(*) FROM return_records WHERE student_id = :s",
            {"s": "stu_synth_0001"},
        ) == 1

        again = _scan(client, issued, when + timedelta(seconds=30))
        assert again["duplicate"] is True
        assert again["return_id"] == result["return_id"]
        assert _count(
            "SELECT count(*) FROM return_records WHERE student_id = :s",
            {"s": "stu_synth_0001"},
        ) == 1
    finally:
        _purge("rsv_synth_test_0001", "stu_synth_0001")


def test_the_code_lives_three_hundred_seconds(client) -> None:
    when = jump_clock(client, 0, 40)
    first = _issue(client, when, reservation_id="rsv_synth_test_0002")
    stale = _issue(
        client, when, student_id="stu_synth_0002", reservation_id="rsv_synth_test_0003"
    )
    try:
        assert (
            _scan(client, first, when + timedelta(seconds=299))["attempt_status"]
            == "SUCCEEDED"
        )
        assert (
            _count(
                "SELECT count(*) FROM pass_codes WHERE reservation_id = :r AND status = 'CONSUMED'",
                {"r": "rsv_synth_test_0002"},
            )
            == 1
        )
        with pytest.raises(ApiError) as late:
            _scan(client, stale, when + timedelta(seconds=300))
        assert late.value.code == "PASS_EXPIRED"
        assert late.value.status_code == 410
        assert (
            _count(
                "SELECT count(*) FROM pass_codes WHERE reservation_id = :r AND status = 'EXPIRED'",
                {"r": "rsv_synth_test_0003"},
            )
            == 1
        )
        assert (
            _count(
                "SELECT count(*) FROM return_records WHERE student_id = :s",
                {"s": "stu_synth_0002"},
            )
            == 0
        )
    finally:
        _purge("rsv_synth_test_0002", "stu_synth_0001")
        _purge("rsv_synth_test_0003", "stu_synth_0002")


def test_the_night_window_closes_at_six_but_the_code_is_still_intact(client) -> None:
    when = jump_clock(client, 5, 58)
    issued = _issue(client, when)
    midnight_end = when.replace(hour=6, minute=0, second=0, microsecond=0)
    try:
        with pytest.raises(ApiError) as ended:
            _scan(client, issued, midnight_end)
        assert ended.value.code == "NIGHT_ACCESS_ENDED"
        assert ended.value.status_code == 403
        assert _count(
            "SELECT count(*) FROM return_records WHERE student_id = :s",
            {"s": "stu_synth_0001"},
        ) == 0
        with get_engine().connect() as conn:
            status = conn.execute(
                text("SELECT status FROM pass_codes WHERE pass_id = :p"),
                {"p": issued["pass_id"]},
            ).scalar()
        assert status == "ISSUED"
    finally:
        _purge("rsv_synth_test_0001", "stu_synth_0001")


def test_an_old_code_never_opens_the_following_night(client) -> None:
    when = jump_clock(client, 0, 40)
    issued = _issue(client, when)
    try:
        with pytest.raises(ApiError) as stale:
            _scan(client, issued, when + timedelta(days=1))
        assert stale.value.code == "PASS_EXPIRED"
        assert (
            _count(
                "SELECT count(*) FROM return_records WHERE student_id = :s AND service_date = :d",
                {"s": "stu_synth_0001", "d": issued["service_date"]},
            )
            == 0
        )
    finally:
        _purge("rsv_synth_test_0001", "stu_synth_0001")


def test_the_terminal_must_prove_who_it_is(client) -> None:
    when = jump_clock(client, 0, 40)
    issued = _issue(client, when)
    try:
        with pytest.raises(ApiError) as bad:
            access.consume("dev_synth_a1_01", "wrong-device-token", issued["token"], when)
        assert bad.value.code == "DEVICE_UNAUTHORIZED"
        assert bad.value.status_code == 401
        with pytest.raises(ApiError) as unknown:
            access.consume("dev_synth_9999", DEVICE_TOKEN["dev_synth_a1_01"], issued["token"], when)
        assert unknown.value.code == "DEVICE_UNKNOWN"
        with pytest.raises(ApiError) as forged:
            access.consume("dev_synth_a1_01", DEVICE_TOKEN["dev_synth_a1_01"], "not-a-pass", when)
        assert forged.value.code == "PASS_NOT_FOUND"
    finally:
        _purge("rsv_synth_test_0001", "stu_synth_0001")


def test_a_code_for_a1_does_not_open_the_a2_terminal(client) -> None:
    when = jump_clock(client, 0, 40)
    issued = _issue(client, when)
    try:
        with pytest.raises(ApiError) as mismatch:
            _scan(client, issued, when, device="dev_synth_a2_01")
        assert mismatch.value.code == "GATE_MISMATCH"
        assert mismatch.value.status_code == 403
    finally:
        _purge("rsv_synth_test_0001", "stu_synth_0001")


def test_reissuing_replaces_the_old_code_and_the_old_one_stops_working(client) -> None:
    when = jump_clock(client, 0, 40)
    first = _issue(client, when)
    second = _issue(
        client, when + timedelta(minutes=10), reservation_id="rsv_synth_test_0002"
    )
    try:
        assert first["pass_id"] != second["pass_id"]
        assert (
            _count(
                "SELECT count(*) FROM pass_codes WHERE reservation_id = :r AND status = 'ISSUED'",
                {"r": "rsv_synth_test_0001"},
            )
            == 1
        )
        assert access.revoke_passes("rsv_synth_test_0001") == 1
        assert (
            _count(
                "SELECT count(*) FROM pass_codes WHERE reservation_id = :r AND status = 'ISSUED'",
                {"r": "rsv_synth_test_0001"},
            )
            == 0
        )
        with pytest.raises(ApiError) as revoked:
            _scan(client, first, when)
        assert revoked.value.code == "PASS_REVOKED"
        assert (
            _count(
                "SELECT count(*) FROM return_records WHERE student_id = :s",
                {"s": "stu_synth_0001"},
            )
            == 0
        )
        result = _scan(client, second, when)
        assert result["attempt_status"] == "SUCCEEDED"
    finally:
        _purge("rsv_synth_test_0001", "stu_synth_0001")
        _purge("rsv_synth_test_0002", "stu_synth_0001")


def test_manual_record_and_a_scan_leave_exactly_one_return(client) -> None:
    when = jump_clock(client, 0, 40)
    token = token_for(client, "dorm")
    recorded = client.post(
        f"{API}/return-records/manual",
        headers=auth(token),
        json={
            "student_id": "stu_synth_0001",
            "building_id": "bldg_a1",
            "occurred_at": when.isoformat(),
            "evidence": {"note": "按门铃后手动开门"},
            "idempotency_key": "manual_test_0001",
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["source"] == "MANUAL"
    assert body["occurred_at"] == when.isoformat()
    assert body["evidence"]["recorded_by"] == "usr_synth_0003"
    try:
        replay = client.post(
            f"{API}/return-records/manual",
            headers=auth(token),
            json={
                "student_id": "stu_synth_0001",
                "building_id": "bldg_a1",
                "occurred_at": when.isoformat(),
                "evidence": {"note": "同一回执重放"},
                "idempotency_key": "manual_test_0001",
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["return_id"] == body["return_id"]

        issued = _issue(client, when)
        with pytest.raises(ApiError) as blocked:
            _scan(client, issued, when)
        assert blocked.value.code == "RETURN_EXISTS"
        assert _count(
            "SELECT count(*) FROM return_records WHERE student_id = :s",
            {"s": "stu_synth_0001"},
        ) == 1
    finally:
        with get_engine().begin() as conn:
            conn.execute(
                text("DELETE FROM return_records WHERE idempotency_key = :k"),
                {"k": "manual_test_0001"},
            )
        _purge("rsv_synth_test_0001", "stu_synth_0001")


def test_the_report_lists_code_returns_and_manual_returns_once_each(client) -> None:
    """返宿记录页既要显示二维码使用情况，也要显示无码的人工补录。"""
    when = jump_clock(client, 0, 40)
    dorm = token_for(client, "dorm")
    issued = _issue(client, when, student_id="stu_synth_0002", reservation_id="rsv_synth_test_0004")
    night = issued["service_date"]
    _scan(client, issued, when)
    manual = client.post(
        f"{API}/return-records/manual",
        headers=auth(dorm),
        json={
            "student_id": "stu_synth_0004",
            "building_id": "bldg_a1",
            "occurred_at": when.isoformat(),
            "evidence": {"note": "按门铃"},
            "idempotency_key": "manual_test_report",
        },
    )
    assert manual.status_code == 200, manual.text
    try:
        body = client.get(
            f"{API}/return-records",
            headers=auth(dorm),
            params={"service_date": night, "building_id": "bldg_a1"},
        ).json()
        by_student = {item["student_id"]: item for item in body["items"]}
        assert by_student["stu_synth_0002"]["pass_status"] == "CONSUMED"
        assert by_student["stu_synth_0002"]["return_source"] == "QR"
        # 人工补录没有码：二维码字段为空，但返宿事实照样进表。
        assert by_student["stu_synth_0004"]["pass_status"] is None
        assert by_student["stu_synth_0004"]["pass_id"] is None
        assert by_student["stu_synth_0004"]["return_source"] == "MANUAL"
        assert body["counters"]["returned"] == 2
        # 一条返宿只出现一次，核销过的码不会因 union 重复。
        ids = [item["return_id"] for item in body["items"] if item["return_id"]]
        assert len(ids) == len(set(ids)) == 2
    finally:
        with get_engine().begin() as conn:
            conn.execute(
                text("DELETE FROM return_records WHERE idempotency_key = :k"),
                {"k": "manual_test_report"},
            )
        _purge("rsv_synth_test_0004", "stu_synth_0002")


def test_manual_record_needs_the_duty_building(client) -> None:
    jump_clock(client, 22, 59)
    token = token_for(client, "dorm")
    outside = client.post(
        f"{API}/return-records/manual",
        headers=auth(token),
        json={
            "student_id": "stu_synth_0013",
            "building_id": "bldg_a2",
            "evidence": {"note": "代班尚未生效"},
        },
    )
    assert outside.status_code == 403
    assert outside.json()["code"] == "OUT_OF_SCOPE"

    student = token_for(client, "student")
    forbidden = client.post(
        f"{API}/return-records/manual",
        headers=auth(student),
        json={"student_id": "stu_synth_0001", "building_id": "bldg_a1", "evidence": {}},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ACTION"


def test_usage_report_is_scoped_by_role(client) -> None:
    when = jump_clock(client, 0, 40)
    issued = _issue(client, when)
    try:
        _scan(client, issued, when)
        night = issued["service_date"]
        token = token_for(client, "dorm")
        report = client.get(
            f"{API}/return-records",
            headers=auth(token),
            params={"service_date": night, "building_id": "bldg_a1"},
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["service_date"] == night
        assert body["counters"]["consumed"] == 1
        assert [item["pass_status"] for item in body["items"]] == ["CONSUMED"]
        assert all(item["building_id"] == "bldg_a1" for item in body["items"])
        assert body["items"][0]["return_id"], body["items"][0]

        counselor = token_for(client, "counselor")
        scoped = client.get(
            f"{API}/return-records", headers=auth(counselor), params={"service_date": night}
        )
        assert scoped.status_code == 200, scoped.text
        assert all(
            item["student_id"] in {f"stu_synth_{index:04d}" for index in range(1, 7)}
            for item in scoped.json()["items"]
        )

        campus = token_for(client, "campus")
        refused = client.get(f"{API}/return-records", headers=auth(campus))
        assert refused.status_code == 403
        assert refused.json()["code"] == "FORBIDDEN_ACTION"

        student = token_for(client, "student")
        denied = client.get(f"{API}/return-records", headers=auth(student))
        assert denied.status_code == 403
        assert denied.json()["code"] == "FORBIDDEN_ACTION"
    finally:
        with get_engine().begin() as conn:
            conn.execute(
                text("DELETE FROM return_records WHERE student_id = :s"),
                {"s": "stu_synth_0001"},
            )
        _purge("rsv_synth_test_0001", "stu_synth_0001")
