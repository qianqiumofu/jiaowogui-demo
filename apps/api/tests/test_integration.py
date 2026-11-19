"""A/B 接缝验收：真实 PG、实际领域服务，不用对方模块的桩冒充联调。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.db import get_engine
from app.core.errors import ApiError
from app.db.models import BackgroundJob, Notification, Reservation
from app.modules.access import service as access
from app.modules.building_list import service as building_list
from app.modules.notification import handlers
from app.modules.reservation import service as reservation
from app.modules.returns import service as returns
from app.modules.statistics import service as statistics
from app.worker.main import run_once
from tests.conftest import API, auth, token_for

pytestmark = pytest.mark.usefixtures("clean_db")
TZ = ZoneInfo("Asia/Shanghai")
NIGHT = date(2026, 11, 15)
PLANNED = datetime(2026, 11, 16, 0, 40, tzinfo=TZ)


class FixedClock(Clock):
    def __init__(self, moment):
        super().__init__("Asia/Shanghai")
        self.moment = moment

    def now(self):
        return self.moment


@pytest.fixture()
def clock(client, monkeypatch):
    clock = FixedClock(datetime(2026, 11, 15, 22, tzinfo=TZ))
    client.app.state.clock = clock
    client.app.state.session_store._clock = clock
    monkeypatch.setattr(handlers, "build_clock", lambda: clock)
    monkeypatch.setattr("app.core.clock.build_clock", lambda: clock)
    return clock


def create(client):
    response = client.post(f"{API}/reservations", headers=auth(token_for(client, "student")),
                           json={"planned_return_at": PLANNED.isoformat()})
    assert response.status_code == 201, response.text
    return response.json()


def issue(res):
    import uuid
    from app.db.models import VerificationSession
    verification_id="vs_"+uuid.uuid4().hex[:24]
    with Session(get_engine()) as db:
        db.add(VerificationSession(id=verification_id,reservation_id=res["id"],student_id=res["student_id"],reservation_version=res["version"],status="SUCCEEDED",face_result=True,presence_result=True,created_at=PLANNED))
        db.commit()
    return access.issue_pass(res["id"], res["version"], {
        "student_id": res["student_id"], "building_id": "bldg_a1",
        "verification_id": verification_id, "planned_return_at": PLANNED.isoformat(),
        "window_start": (PLANNED - timedelta(minutes=30)).isoformat(),
        "window_end": (PLANNED + timedelta(minutes=30)).isoformat(),
        "verified_at": PLANNED.isoformat(), "gate_id": "gate_a1_north",
    })


def test_concurrent_issue_keeps_only_one_active_code(client, clock):
    res = create(client)
    barrier = Barrier(2)
    def sign():
        barrier.wait(timeout=10)
        return issue(res)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(sign), pool.submit(sign)
        codes = [a.result(timeout=20), b.result(timeout=20)]
    assert codes[0]["pass_id"] != codes[1]["pass_id"]
    with get_engine().connect() as conn:
        states = conn.execute(text("SELECT status FROM pass_codes WHERE reservation_id=:r"), {"r": res["id"]}).scalars().all()
    assert sorted(states) == ["ISSUED", "REVOKED"]


@pytest.mark.parametrize("moment,expected", [
    (datetime(2026, 11, 15, 23, 59, 59, tzinfo=TZ), 201),
    (datetime(2026, 11, 16, 0, 0, tzinfo=TZ), 409),
    (datetime(2026, 11, 16, 0, 0, 1, tzinfo=TZ), 409),
])
def test_first_application_cutoff_is_server_side(client, clock, moment, expected):
    clock.moment = moment
    response = client.post(f"{API}/reservations", headers=auth(token_for(client, "student")),
                           json={"planned_return_at": PLANNED.isoformat()})
    assert response.status_code == expected, response.text
    if expected == 409:
        assert response.json()["code"] == "RESERVATION_CREATION_CLOSED"
        with Session(get_engine()) as db:
            assert list(db.scalars(select(BackgroundJob))) == []


def test_real_roster_snapshot_change_and_notification_chain(client, clock):
    res = create(client)
    assert building_list.tonight("bldg_a1", clock.now())["items"][0]["reservation_version"] == 1
    assert run_once(clock, timedelta(seconds=60)) == 1
    clock.moment = datetime(2026, 11, 16, 0, 0, tzinfo=TZ)
    assert building_list.run_snapshot("bldg_a1", NIGHT) == 1
    assert building_list.run_snapshot("bldg_a1", NIGHT) == 1
    assert run_once(clock, timedelta(seconds=60)) == 1
    student = token_for(client, "student")
    changed = client.patch(f"{API}/reservations/{res['id']}", headers=auth(student), json={
        "expected_version": 1, "planned_return_at": "2026-11-16T02:00:00+08:00"})
    assert changed.status_code == 200, changed.text
    assert run_once(clock, timedelta(seconds=60)) == 1
    row = building_list.tonight("bldg_a1", clock.now())["items"][0]
    assert row["change_flag"] == "RESCHEDULED" and row["reservation_version"] == 2
    with Session(get_engine()) as db:
        items = list(db.scalars(select(Notification)))
        assert sorted(n.template for n in items) == ["DORM_APPROVED", "DORM_RESCHEDULED", "NIGHT_ROSTER"]
        assert {n.recipient_user_id for n in items} == {"usr_synth_0003"}
        assert {n.channel for n in items} == {"INBOX"}
        assert all(n.recipient_email is None for n in items)
        assert len([n for n in items if "已汇总" in n.subject]) == 1
    assert run_once(clock, timedelta(seconds=60)) == 0


def test_reschedule_revokes_old_pass_in_same_transaction(client, clock):
    res = create(client)
    old = issue(res)
    changed = client.patch(f"{API}/reservations/{res['id']}", headers=auth(token_for(client, "student")),
                           json={"expected_version": 1, "reason": "更新合成原因"})
    assert changed.status_code == 200
    with pytest.raises(ApiError) as blocked:
        access.consume("dev_synth_a1_01", "dev_synth:dev_synth_a1_01", old["token"], PLANNED)
    assert blocked.value.code == "PASS_REVOKED"
    with get_engine().connect() as conn:
        assert returns.find_for_night(conn, res["student_id"], NIGHT) is None


def test_return_fulfills_reservation_and_rolls_back_with_caller(client, clock):
    res = create(client)
    with pytest.raises(RuntimeError):
        with get_engine().begin() as conn:
            returns.confirm_return(conn, res["student_id"], NIGHT, "MANUAL", {}, PLANNED, "rollback_synth")
            raise RuntimeError("故意回滚整个调用方事务")
    with Session(get_engine()) as db:
        assert db.get(Reservation, res["id"]).status == "ACTIVE"
        assert returns.find_for_night(db.connection(), res["student_id"], NIGHT) is None
    with get_engine().begin() as conn:
        returns.confirm_return(conn, res["student_id"], NIGHT, "MANUAL", {}, PLANNED, "commit_synth")
    with Session(get_engine()) as db:
        assert db.get(Reservation, res["id"]).status == "FULFILLED"
    blocked = client.patch(f"{API}/reservations/{res['id']}", headers=auth(token_for(client, "student")),
                           json={"expected_version": 1, "reason": "返宿后不可改"})
    assert blocked.status_code == 409


def test_scan_and_manual_entry_race_share_the_same_night_lock(client, clock):
    res = create(client)
    issued = issue(res)
    barrier = Barrier(2)

    def scan():
        barrier.wait(timeout=10)
        try:
            return access.consume("dev_synth_a1_01", "dev_synth:dev_synth_a1_01", issued["token"], PLANNED)
        except ApiError as exc:
            return exc.code

    def manual():
        barrier.wait(timeout=10)
        with get_engine().begin() as conn:
            return returns.confirm_return(conn, res["student_id"], NIGHT, "MANUAL", {}, PLANNED, "race_synth")

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(scan), pool.submit(manual)
        result, return_id = a.result(timeout=20), b.result(timeout=20)
    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT return_id, source FROM return_records WHERE student_id=:s AND service_date=:d"),
                            {"s": res["student_id"], "d": NIGHT}).mappings().all()
        assert len(rows) == 1 and rows[0]["return_id"] == return_id
        if isinstance(result, dict):
            assert rows[0]["source"] == "QR" and result["return_id"] == return_id
        else:
            assert result in ("RETURN_EXISTS", "PASS_REVOKED") and rows[0]["source"] == "MANUAL"


def test_statistics_reads_real_reservations_and_formal_returns(client, clock):
    res = create(client)
    with get_engine().connect() as conn:
        before = statistics.query(conn, date_from=NIGHT.isoformat(), date_to=NIGHT.isoformat(), group_by="building")
    assert before["totals"]["reservations"] == before["totals"]["unconfirmed"] == 1
    assert before["totals"]["returns"] == 0 and before["data_gaps"] == []
    with get_engine().begin() as conn:
        returns.confirm_return(conn, res["student_id"], NIGHT, "MANUAL", {}, PLANNED, "stats_synth")
    with get_engine().connect() as conn:
        after = statistics.query(conn, date_from=NIGHT.isoformat(), date_to=NIGHT.isoformat(), group_by="building")
    assert after["totals"]["reservations"] == after["totals"]["returns"] == 1
    assert after["totals"]["unconfirmed"] == 0
    assert after["by_day"][0]["unconfirmed"] == after["rows"][0]["unconfirmed"] == 0


def test_scope_is_applied_even_when_building_filter_is_omitted(client, clock):
    campus = token_for(client, "campus")
    created = client.post(f"{API}/staff-accounts", headers=auth(campus), json={
        "login_name": "synth_a2", "display_name": "合成宿管", "building_ids": ["bldg_a2"]}).json()
    login = client.post(f"{API}/auth/mock-login", json={"login_name": "synth_a2", "password": created["initial_password"]}).json()
    create(client)
    with get_engine().begin() as conn:
        for student in ("stu_synth_0001", "stu_synth_0013"):
            returns.confirm_return(conn, student, NIGHT, "MANUAL", {}, PLANNED, f"scope_synth:{student}")
    records = client.get(f"{API}/return-records?service_date={NIGHT}", headers=auth(login["token"]))
    assert records.status_code == 200
    assert [r["student_id"] for r in records.json()["items"]] == ["stu_synth_0013"]
    reservations = client.get(f"{API}/reservations", headers=auth(login["token"]))
    assert reservations.status_code == 200 and reservations.json()["items"] == []


def test_no_timeout_notification_after_return_or_query(client, clock):
    res = create(client)
    run_once(clock, timedelta(seconds=60))
    with Session(get_engine()) as db:
        keys = set(db.scalars(select(BackgroundJob.business_key)))
    clock.moment = datetime(2026, 11, 16, 4, tzinfo=TZ)
    client.get(f"{API}/reservations", headers=auth(token_for(client, "student")))
    building_list.tonight("bldg_a1", clock.now())
    with Session(get_engine()) as db:
        assert set(db.scalars(select(BackgroundJob.business_key))) == keys
        assert {n.template for n in db.scalars(select(Notification))} == {"DORM_APPROVED"}


def test_seed_dorm_account_obeys_database_password_and_disable(client, clock):
    campus = token_for(client, "campus")
    old = token_for(client, "dorm")
    try:
        reset = client.post(f"{API}/staff-accounts/usr_synth_0003/reset-password", headers=auth(campus))
        assert reset.status_code == 200
        assert client.get(f"{API}/me", headers=auth(old)).status_code == 401
        assert client.post(f"{API}/auth/mock-login", json={"login_name": "dorm", "password": "demo1234"}).status_code == 401
        fresh = client.post(f"{API}/auth/mock-login", json={"login_name": "dorm", "password": reset.json()["initial_password"]})
        assert fresh.status_code == 200
        disabled = client.post(f"{API}/staff-accounts/usr_synth_0003/disable", headers=auth(campus))
        assert disabled.status_code == 200
        blocked = client.post(f"{API}/auth/mock-login", json={"login_name": "dorm", "password": reset.json()["initial_password"]})
        assert blocked.status_code == 403 and blocked.json()["code"] == "ACCOUNT_DISABLED"
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE users SET password='demo1234', status='ACTIVE', disabled_at=NULL WHERE user_id='usr_synth_0003'"))


def test_manual_entry_cannot_claim_another_building_and_preserves_recording_time(client, clock):
    clock.moment = datetime(2026, 11, 16, 1, tzinfo=TZ)
    dorm = token_for(client, "dorm")
    wrong = client.post(f"{API}/return-records/manual", headers=auth(dorm), json={
        "student_id": "stu_synth_0025", "building_id": "bldg_a1", "idempotency_key": "synth_forged"})
    assert wrong.status_code == 403 and wrong.json()["code"] == "OUT_OF_SCOPE"
    response = client.post(f"{API}/return-records/manual", headers=auth(dorm), json={
        "student_id": "stu_synth_0001", "building_id": "bldg_a1", "occurred_at": PLANNED.isoformat(),
        "idempotency_key": "synth_backfill"})
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["occurred_at"]) == PLANNED
    assert datetime.fromisoformat(response.json()["recorded_at"]) == clock.now()
