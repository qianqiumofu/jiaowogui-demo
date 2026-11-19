"""预约 M2 场景：时间边界、权限、并发与唯一约束。全部需要真实 PostgreSQL。"""

import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import service_date_of
from tests.conftest import API, auth, token_for

TZ = ZoneInfo("Asia/Shanghai")

pytestmark = pytest.mark.usefixtures("clean_db")


def now_bj() -> datetime:
    return datetime(2026,11,15,18,0,tzinfo=TZ)


def service_today() -> date:
    return service_date_of(now_bj())


def gate_time(hour: int, minute: int = 0) -> datetime:
    """本业务夜门禁时段内的时刻（D+1 凌晨）。"""
    return datetime.combine(service_today() + timedelta(days=1), time(hour, minute), TZ)


def create(client: TestClient, token: str, hour: int = 1, minute: int = 30, reason: str = "") -> dict:
    response = client.post(
        f"{API}/reservations",
        json={"planned_return_at": gate_time(hour, minute).isoformat(), "reason": reason},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def offset_clock(client: TestClient, target: datetime) -> None:
    minutes = int((target - datetime.now(TZ)).total_seconds() // 60)
    response = client.post(f"{API}/demo/clock", json={"offset_minutes": minutes})
    assert response.status_code == 200


def test_create_then_list_and_revision_shape(client, student_token) -> None:
    assert client.get(f"{API}/reservations/tonight", headers=auth(student_token)).json() is None

    res = create(client, student_token, reason="实验室跑数据")
    assert res["status"] == "ACTIVE" and res["version"] == 1
    assert res["student_id"] == "stu_synth_0001"
    assert res["service_date"] == service_today().isoformat()

    tonight = client.get(f"{API}/reservations/tonight", headers=auth(student_token)).json()
    assert tonight["id"] == res["id"]

    listed = client.get(f"{API}/reservations", headers=auth(student_token)).json()
    assert [item["id"] for item in listed["items"]] == [res["id"]]

    revs = client.get(f"{API}/reservations/{res['id']}/revisions", headers=auth(student_token)).json()
    assert [(r["version"], r["source"]) for r in revs["items"]] == [(1, "CREATE")]

    dorm = token_for(client, "dorm")
    denied = client.get(f"{API}/reservations/tonight", headers=auth(dorm))
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN_ACTION"


def test_second_create_same_night_conflicts(client, student_token) -> None:
    res = create(client, student_token)
    again = client.post(
        f"{API}/reservations",
        json={"planned_return_at": gate_time(2, 0).isoformat()},
        headers=auth(student_token),
    )
    assert again.status_code == 409
    body = again.json()
    assert body["code"] == "RESERVATION_EXISTS"
    assert body["details"]["reservation_id"] == res["id"]


@pytest.mark.parametrize(
    ("hour", "minute", "valid"),
    [(0, 0, True), (5, 30, True), (5, 45, False), (6, 0, False), (23, 30, False)],
)
def test_planned_must_be_inside_gate_window(client, student_token, hour, minute, valid) -> None:
    response = client.post(
        f"{API}/reservations",
        json={"planned_return_at": gate_time(hour, minute).isoformat()},
        headers=auth(student_token),
    )
    if valid:
        assert response.status_code == 201
    else:
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


def test_reschedule_unlimited_with_full_history(client, student_token) -> None:
    res = create(client, student_token, hour=1, minute=30)
    rid = res["id"]

    for hour, minute, expected in [(3, 0, 1), (4, 15, 2)]:
        patched = client.patch(
            f"{API}/reservations/{rid}",
            json={
                "expected_version": expected,
                "planned_return_at": gate_time(hour, minute).isoformat(),
            },
            headers=auth(student_token),
        )
        assert patched.status_code == 200, patched.text

    # R07：超过原预约时间仍可改期——推进到原计划之后、最晚可选时刻（05:30）之前。
    offset_clock(client, gate_time(5, 0))
    late = client.patch(
        f"{API}/reservations/{rid}",
        json={"expected_version": 3, "planned_return_at": gate_time(5, 30).isoformat()},
        headers=auth(student_token),
    )
    assert late.status_code == 200
    assert late.json()["version"] == 4

    revs = client.get(f"{API}/reservations/{rid}/revisions", headers=auth(student_token)).json()
    assert [(r["version"], r["source"]) for r in revs["items"]] == [
        (1, "CREATE"), (2, "RESCHEDULE"), (3, "RESCHEDULE"), (4, "RESCHEDULE"),
    ]


def test_stale_expected_version_rejected(client, student_token) -> None:
    res = create(client, student_token)
    client.patch(
        f"{API}/reservations/{res['id']}",
        json={"expected_version": 1, "reason": "改晚一点"},
        headers=auth(student_token),
    )
    stale = client.patch(
        f"{API}/reservations/{res['id']}",
        json={"expected_version": 1, "reason": "并发对手"},
        headers=auth(student_token),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert stale.json()["details"] == {"expected_version": 1, "current_version": 2}


def test_cancel_then_restore_reuses_same_id(client, student_token) -> None:
    res = create(client, student_token)
    cancelled = client.post(
        f"{API}/reservations/{res['id']}/cancel",
        json={"expected_version": 1},
        headers=auth(student_token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    fresh = client.post(
        f"{API}/reservations",
        json={"planned_return_at": gate_time(2, 0).isoformat()},
        headers=auth(student_token),
    )
    assert fresh.status_code == 409
    assert fresh.json()["code"] == "RESERVATION_CANCELLED"

    restored = client.post(
        f"{API}/reservations/{res['id']}/restore",
        json={"expected_version": 2},
        headers=auth(student_token),
    )
    assert restored.status_code == 200
    assert restored.json()["id"] == res["id"]
    assert restored.json()["status"] == "ACTIVE"
    assert restored.json()["version"] == 3


def test_planned_time_keeps_business_offset(client, student_token) -> None:
    res = create(client, student_token, hour=2, minute=40)
    cancelled = client.post(
        f"{API}/reservations/{res['id']}/cancel",
        json={"expected_version": 1},
        headers=auth(student_token),
    )
    restored = client.post(
        f"{API}/reservations/{res['id']}/restore",
        json={"expected_version": 2},
        headers=auth(student_token),
    )
    tonight = client.get(f"{API}/reservations/tonight", headers=auth(student_token)).json()

    moments = [
        res["planned_return_at"],
        cancelled.json()["planned_return_at"],
        restored.json()["planned_return_at"],
        tonight["planned_return_at"],
    ]
    # 库里回读是 UTC，入参带业务时区；响应统一换成业务偏移，前端才显示成同一时刻。
    assert {moment[-6:] for moment in moments} == {"+08:00"}
    assert {datetime.fromisoformat(moment) for moment in moments} == {gate_time(2, 40)}


def test_after_night_closed_no_mutation(client, student_token) -> None:
    res = create(client, student_token, hour=1, minute=30)
    ended = datetime.combine(service_today() + timedelta(days=1), time(6, 10), TZ)
    offset_clock(client, ended)

    listed = client.get(f"{API}/reservations", headers=auth(student_token)).json()
    assert listed["items"][0]["status"] == "CLOSED"

    patched = client.patch(
        f"{API}/reservations/{res['id']}",
        json={"expected_version": 1, "planned_return_at": gate_time(1, 0).isoformat()},
        headers=auth(student_token),
    )
    assert patched.status_code == 409
    assert patched.json()["code"] == "RESERVATION_NOT_EDITABLE"
    assert patched.json()["details"]["status"] == "CLOSED"


def test_cross_student_access_is_404_and_roles_denied(client, student_token) -> None:
    res = create(client, student_token)

    # counselor 切到 STUDENT 角色，是另一个学生（stu_synth_0009）。
    counselor = token_for(client, "counselor")
    as_student = client.post(f"{API}/auth/role-switch", json={"role": "STUDENT"}, headers=auth(counselor))
    other_token = as_student.json()["token"]

    stolen = client.patch(
        f"{API}/reservations/{res['id']}",
        json={"expected_version": 1, "reason": "越权改他人预约"},
        headers=auth(other_token),
    )
    assert stolen.status_code == 404
    assert stolen.json()["code"] == "RESERVATION_NOT_FOUND"

    dorm = token_for(client, "dorm")
    created = client.post(
        f"{API}/reservations",
        json={"planned_return_at": gate_time(1, 0).isoformat()},
        headers=auth(dorm),
    )
    assert created.status_code == 403
    assert created.json()["code"] == "FORBIDDEN_ACTION"


@pytest.mark.parametrize("login", ["counselor", "dorm"])
def test_pending_directory_denies_instead_of_empty_list(client, login, monkeypatch) -> None:
    from app.modules.directory import service as directory
    monkeypatch.setattr(directory, "get_assigned_students", lambda *args: [])
    monkeypatch.setattr(directory, "get_duty_buildings", lambda *args: [])
    token = token_for(client, login)
    listed = client.get(f"{API}/reservations", headers=auth(token))
    assert listed.status_code == 403
    assert listed.json()["code"] == "SCOPE_UNRESOLVED"


def test_concurrent_create_yields_single_row(client) -> None:
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from app.core.clock import build_clock
    from app.core.db import get_engine
    from app.core.errors import ApiError
    from app.db.models import Reservation
    from app.modules.reservation import service

    factory = sessionmaker(get_engine(), expire_on_commit=False)
    clock = build_clock()
    planned = gate_time(1, 30)
    barrier = threading.Barrier(2, timeout=5)
    outcomes: list[tuple[str, str]] = []

    def worker() -> None:
        session = factory()
        try:
            barrier.wait()
            res = service.create_reservation(
                session,
                clock,
                student_id="stu_synth_0001",
                school_id="2023S0001",
                actor_user_id="usr_synth_0001",
                planned_return_at=planned,
                reason="并发",
            )
            outcomes.append(("ok", res.id))
        except ApiError as exc:
            outcomes.append(("err", exc.code))
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    verify = factory()
    try:
        rows = verify.scalar(select(func.count()).select_from(Reservation))
    finally:
        verify.close()

    assert rows == 1
    assert sum(1 for kind, _ in outcomes if kind == "ok") == 1
    assert [code for kind, code in outcomes if kind == "err"] == ["RESERVATION_EXISTS"]


def test_reason_length_is_configurable_limit(client, student_token) -> None:
    from app.core.config import get_settings

    limit = get_settings().reservation_reason_max_chars
    response = client.post(
        f"{API}/reservations",
        json={"planned_return_at": gate_time(1, 30).isoformat(), "reason": "晚" * (limit + 1)},
        headers=auth(student_token),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["max_length"] == limit
