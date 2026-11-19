"""今晚名单：24:00 汇总边界、当夜过滤、异动标记、推送装配与联系方式字段级权限。"""

import sys
import types
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from tests.conftest import API, auth, jump_clock, token_for

TZ = ZoneInfo("Asia/Shanghai")
NIGHT = date(2026, 11, 15)
NIGHT_TEXT = NIGHT.isoformat()


import pytest

pytestmark = pytest.mark.usefixtures("seeded_demo_db")

def _resident(student_id: str = "stu_synth_0001", room: str = "A1-301") -> dict:
    return {
        "student_id": student_id,
        "school_id": f"{student_id[-4:]}S2024",
        "display_name": "合成学生",
        "room_no": room,
        "college_name": "合成学院",
        "grade": "2024",
    }


def _reservation(**changes) -> dict:
    base = {
        "student_id": "stu_synth_0001",
        "service_date": NIGHT_TEXT,
        "planned_return_at": "2026-11-16T00:40:00+08:00",
        "status": "ACTIVE",
        "version": 1,
        "updated_at": "2026-11-16T00:05:00+08:00",
    }
    return {**base, **changes}


def test_summary_moment_is_midnight_of_the_business_night() -> None:
    from app.core.clock import is_summary_passed, service_date_of, summary_moment

    moment = summary_moment(NIGHT, TZ)
    assert moment == datetime(2026, 11, 16, 0, 0, tzinfo=TZ)
    # 24:00 仍属业务夜 11 月 15 日，门禁时段此刻正好开启。
    assert service_date_of(moment) == NIGHT

    assert not is_summary_passed(moment - timedelta(minutes=1), NIGHT)
    assert is_summary_passed(moment, NIGHT)
    assert is_summary_passed(moment + timedelta(hours=3), NIGHT)


def test_the_cutoff_closes_only_the_night_being_applied_for() -> None:
    """24:00 关掉的是「那一夜」的首次申请，次夜同一时刻仍然可以提交。"""
    from app.core.clock import is_summary_passed

    just_after_midnight = datetime(2026, 11, 16, 0, 30, tzinfo=TZ)
    assert is_summary_passed(just_after_midnight, NIGHT) is True
    assert is_summary_passed(just_after_midnight, NIGHT + timedelta(days=1)) is False
    # 不传业务夜时按此刻所属业务夜判定，也就是仍然被关的那一夜。
    assert is_summary_passed(just_after_midnight) is True


def test_items_are_marked_against_the_summary_baseline() -> None:
    from app.modules.building_list.service import build_items

    baseline = [
        {
            "student_id": "stu_synth_0001",
            "planned_return_at": "2026-11-16T00:40:00+08:00",
            "reservation_status": "ACTIVE",
            "reservation_version": 1,
        },
        {
            "student_id": "stu_synth_0002",
            "planned_return_at": "2026-11-16T01:00:00+08:00",
            "reservation_status": "ACTIVE",
            "reservation_version": 1,
        },
    ]
    residents = [_resident()]
    residents.append({**_resident("stu_synth_0002", "A1-302")})
    residents.append({**_resident("stu_synth_0003", "A1-303")})

    items = build_items(
        residents,
        [
            _reservation(),
            {**_reservation(student_id="stu_synth_0002"), "status": "CANCELLED"},
            {**_reservation(student_id="stu_synth_0003"), "version": 2},
        ],
        baseline,
        NIGHT,
        {},
    )

    flags = {item["student_id"]: item["change_flag"] for item in items}
    assert flags["stu_synth_0001"] is None
    assert flags["stu_synth_0002"] == "CANCELLED"
    # 汇总后不应出现新增（A 已拒绝该夜首次申请），仍标出来便于对账。
    assert flags["stu_synth_0003"] == "ADDED_AFTER_SUMMARY"


def test_reschedule_updates_the_flag_and_room_sorts_the_list() -> None:
    from app.modules.building_list.service import build_items

    baseline = [
        {
            "student_id": "stu_synth_0001",
            "planned_return_at": "2026-11-16T00:40:00+08:00",
            "reservation_status": "ACTIVE",
            "reservation_version": 1,
        }
    ]
    items = build_items(
        [_resident(), {**_resident("stu_synth_0009", "A1-302")}],
        [{**_reservation(planned_return_at="2026-11-16T02:10:00+08:00")}],
        baseline,
        NIGHT,
        {},
    )
    assert [item["room_no"] for item in items] == ["A1-301"]
    assert items[0]["change_flag"] == "RESCHEDULED"


def test_reservations_outside_the_roster_do_not_invent_a_room() -> None:
    from app.modules.building_list.service import build_items

    items = build_items(
        [_resident()], [_reservation(student_id="stu_synth_9999")], None, NIGHT, {}
    )
    assert items == []


def test_only_that_nights_reservations_reach_the_list() -> None:
    """需求③：阿姨看到的必须是当夜申请，次夜与缺业务夜的脏数据一律不进名单。"""
    from app.modules.building_list.service import build_items

    next_night = (NIGHT + timedelta(days=1)).isoformat()
    residents = [
        _resident(),
        {**_resident("stu_synth_0002", "A1-302")},
        {**_resident("stu_synth_0003", "A1-303")},
    ]
    items = build_items(
        residents,
        [
            _reservation(),
            _reservation(student_id="stu_synth_0002", service_date=next_night),
            {**_reservation(student_id="stu_synth_0003"), "service_date": None},
        ],
        None,
        NIGHT,
        {},
    )
    assert [item["student_id"] for item in items] == ["stu_synth_0001"]


def test_passage_columns_come_only_from_the_formal_return_record() -> None:
    """需求（g）：门禁通行情况只认 B 的正式记录，A 的 FULFILLED 不算已返宿（R10）。"""
    from app.modules.building_list.service import build_items

    recorded = {
        "stu_synth_0001": {
            "source": "QR",
            "occurred_at": "2026-11-16T00:41:00+08:00",
            "gate_id": "gate_a1_north",
        },
        "stu_synth_0002": {
            "source": "MANUAL",
            "occurred_at": "2026-11-16T01:05:00+08:00",
            "gate_id": None,
        },
    }
    items = build_items(
        [
            _resident(),
            _resident("stu_synth_0002", "A1-302"),
            _resident("stu_synth_0003", "A1-303"),
        ],
        [
            _reservation(),
            _reservation(student_id="stu_synth_0002"),
            _reservation(student_id="stu_synth_0003", status="FULFILLED"),
        ],
        None,
        NIGHT,
        recorded,
    )
    by_id = {item["student_id"]: item for item in items}
    assert by_id["stu_synth_0001"]["return_status"] == "ENTERED"
    assert by_id["stu_synth_0001"]["gate_id"] == "gate_a1_north"
    assert by_id["stu_synth_0002"]["return_status"] == "MANUAL_ENTERED"
    assert by_id["stu_synth_0003"]["return_status"] == "PENDING"
    assert by_id["stu_synth_0003"]["entered_at"] is None


def test_manual_bell_return_without_a_reservation_adds_a_row_at_the_recorded_moment() -> None:
    """需求：按门铃补录的学生进入当夜汇总名单，晚归时间取录入时刻（返宿发生时间）。"""
    from app.modules.building_list.service import build_items

    recorded_occurred = "2026-11-16T00:48:00+08:00"
    returned = {
        "stu_synth_0005": {
            "source": "MANUAL",
            "occurred_at": recorded_occurred,
            "gate_id": None,
        }
    }
    baseline = [{"student_id": "stu_synth_0001", "planned_return_at": "x", "reservation_status": "ACTIVE", "reservation_version": 1}]
    items = build_items(
        [_resident(), _resident("stu_synth_0005", "A1-305")],
        [_reservation()],
        baseline,
        NIGHT,
        returned,
    )
    by_id = {item["student_id"]: item for item in items}
    manual = by_id["stu_synth_0005"]
    # 补录行没有预约：晚归时间＝录入时刻，状态标 NONE 与人工补录已返。
    assert manual["planned_return_at"] == recorded_occurred
    assert manual["reservation_status"] == "NONE"
    assert manual["return_status"] == "MANUAL_ENTERED"
    assert manual["entered_at"] == recorded_occurred
    assert manual["change_flag"] == "ADDED_AFTER_SUMMARY"
    # 有预约的那条不受影响，仍是单独一行。
    assert by_id["stu_synth_0001"]["reservation_status"] == "ACTIVE"


def test_a_manual_record_for_a_reserved_student_does_not_double_the_row() -> None:
    """已有预约的学生被补录只翻通行状态，不另起一条补录行，避免同一人出现两次。"""
    from app.modules.building_list.service import build_items

    returned = {
        "stu_synth_0001": {
            "source": "MANUAL",
            "occurred_at": "2026-11-16T00:50:00+08:00",
            "gate_id": None,
        }
    }
    items = build_items([_resident()], [_reservation()], None, NIGHT, returned)
    assert [item["student_id"] for item in items] == ["stu_synth_0001"]
    assert items[0]["return_status"] == "MANUAL_ENTERED"
    # 晚归时间仍取预约时间，不被补录录入时刻覆盖。
    assert items[0]["planned_return_at"] == "2026-11-16T00:40:00+08:00"


def test_snapshot_timestamps_leave_the_database_in_business_time(client) -> None:
    from app.core.db import get_engine
    from app.modules.building_list import service as building_list

    day = date(2026, 1, 4)  # 避开演示楼栋的真实夜次，专用测试基准
    anchor = datetime(2026, 1, 5, 0, 0, tzinfo=TZ)
    params = {"b": "bldg_a1", "d": day}
    delete = text("DELETE FROM building_list_snapshots WHERE building_id=:b AND service_date=:d")
    with get_engine().begin() as conn:
        conn.execute(delete, params)
    try:
        building_list.write_snapshot("bldg_a1", day, anchor, [])
        _, generated_at = building_list.load_summary_items("bldg_a1", day)
        assert generated_at is not None
        assert generated_at.endswith("+08:00"), generated_at
    finally:
        with get_engine().begin() as conn:
            conn.execute(delete, params)


def test_tonight_denies_buildings_outside_the_duty_window(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)
    response = client.get(f"{API}/buildings/bldg_a2/tonight", headers=auth(token))
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "OUT_OF_SCOPE"
    assert body["details"]["allowed"] == ["bldg_a1"]


def test_contact_requires_the_duty_window_and_is_field_scoped(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)

    allowed = client.get(
        f"{API}/directory/students/stu_synth_0001/contact", headers=auth(token)
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["building_id"] == "bldg_a1"
    assert body["phone"].startswith("138")
    # 名单不返回学院以外的敏感扩展；联系方式只在此端点出现。
    assert "college_name" not in body

    denied = client.get(
        f"{API}/directory/students/stu_synth_0013/contact", headers=auth(token)
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "OUT_OF_SCOPE"

    student = token_for(client, "student")
    forbidden = client.get(
        f"{API}/directory/students/stu_synth_0001/contact", headers=auth(student)
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ACTION"


def test_contact_opens_up_when_the_substitute_shift_starts(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 22, 59)
    before = client.get(
        f"{API}/directory/students/stu_synth_0013/contact", headers=auth(token)
    )
    assert before.status_code == 403

    jump_clock(client, 23, 1)
    after = client.get(f"{API}/directory/students/stu_synth_0013/contact", headers=auth(token))
    assert after.status_code == 200, after.text
    assert after.json()["building_id"] == "bldg_a2"


ANCHOR = datetime(2026, 11, 16, 0, 0, tzinfo=TZ)


def _event(**changes) -> dict:
    base = {
        "change_kind": "APPROVED",
        "student_id": "stu_synth_0001",
        "building_id": "bldg_a1",
        "planned_return_at": "2026-11-16T01:20:00+08:00",
        "reservation_version": 1,
    }
    return {**base, **changes}


def test_approved_push_carries_every_field_the_dorm_needs() -> None:
    """需求①：寝室号、学号、学院、晚归时间、联系方式一条不缺。"""
    from app.modules.building_list.notify import compose

    message = compose(_event(), ANCHOR)
    for fragment in ("A1-301", "2023S0001", "计算机学院", "2026-11-16T01:20:00+08:00", "13800000001"):
        assert fragment in message["body"], message["body"]
    assert message["template"] == "dorm.reservation.approved"
    assert message["dedup_key"] == "dorm:bldg_a1:stu_synth_0001:APPROVED:1"


def test_change_pushes_stay_short_but_keep_the_flag() -> None:
    from app.modules.building_list.notify import compose

    rescheduled = compose(_event(change_kind="RESCHEDULED", planned_return_at="2026-11-16T02:10:00+08:00", reservation_version=2), ANCHOR)
    assert rescheduled["body"].startswith("【改期】")
    assert "2026-11-16T02:10:00+08:00" in rescheduled["body"]
    assert rescheduled["template"] == "dorm.reservation.rescheduled"

    cancelled = compose(_event(change_kind="CANCELLED", planned_return_at=None, reservation_version=3), ANCHOR)
    assert cancelled["body"].startswith("【撤销】")
    assert "已取消" in cancelled["body"]
    # 撤销不携带联系方式之外的臆造时间。
    assert cancelled["planned_return_at"] is None


def test_push_never_invents_a_room_when_the_directory_is_blank() -> None:
    from app.modules.building_list.notify import compose

    message = compose(_event(student_id="stu_synth_9999", school_id="2099S9999"), ANCHOR)
    assert message["room_no"] == "归属待同步"
    assert message["phone"] is None
    assert "2099S9999" in message["body"]


def test_summary_push_only_counts_that_night_and_is_idempotent() -> None:
    from app.modules.building_list.notify import compose_summary

    items = [{"student_id": "stu_synth_0001"}, {"student_id": "stu_synth_0002"}]
    message = compose_summary("bldg_a1", NIGHT, items, ANCHOR)
    assert message["student_count"] == 2
    assert message["template"] == "dorm.list.summary"
    assert f"{NIGHT_TEXT} 当晚晚归申请共 2 人" in message["body"]
    assert message["dedup_key"] == f"dorm:bldg_a1:{NIGHT_TEXT}:SUMMARY"


def test_push_degrades_to_the_missing_notification_capability(monkeypatch) -> None:
    """A 的 notification.enqueue 未落地时只报 501，不允许静默丢弃消息。"""
    import pytest

    from app.core.errors import ApiError
    from app.modules.building_list import notify

    monkeypatch.setitem(sys.modules, "app.modules.notification.service", types.ModuleType("app.modules.notification.service"))
    for call in (
        lambda: notify.push(_event(), ANCHOR),
        lambda: notify.push_summary("bldg_a1", NIGHT, [], ANCHOR),
    ):
        with pytest.raises(ApiError) as raised:
            call()
        assert raised.value.code == "NOT_IMPLEMENTED"
        assert raised.value.details["capability"] == "notification.enqueue"


def _install_a_stubs(monkeypatch, reservations) -> list[tuple]:
    """把 A 的两个接缝换成桩，让需求②③的链路在 CI 里真正跑通。"""

    def list_for_building(building_id: str, service_date: date) -> list[dict]:
        return [
            row
            for row in reservations
            if row["building_id"] == building_id and row["service_date"] == service_date.isoformat()
        ]

    from app.modules.reservation.service import fulfill_night
    reservation_stub = types.ModuleType("app.modules.reservation.service")
    reservation_stub.list_for_building_at = lambda b,n,at:list_for_building(b,n)
    reservation_stub.list_for_building = list_for_building
    reservation_stub.fulfill_night = fulfill_night
    monkeypatch.setitem(sys.modules, "app.modules.reservation.service", reservation_stub)

    enqueued: list[tuple] = []
    notification_stub = types.ModuleType("app.modules.notification.service")

    def enqueue(template, recipient_ids, payload, dedup_key):
        enqueued.append((template, list(recipient_ids), dedup_key))

    notification_stub.enqueue_building_message = enqueue
    monkeypatch.setitem(sys.modules, "app.modules.notification.service", notification_stub)
    return enqueued


def test_summary_lands_and_pushes_then_live_changes_flag_the_list(client, monkeypatch) -> None:
    """需求②+③：24:00 汇总落库并推送人数，之后改期与撤销实时进名单。"""
    from app.core.db import get_engine
    from app.modules.building_list import service as building_list

    reservations = [
        {
            "building_id": "bldg_a1",
            "student_id": "stu_synth_0001",
            "service_date": NIGHT_TEXT,
            "planned_return_at": "2026-11-16T00:40:00+08:00",
            "status": "ACTIVE",
            "version": 1,
            "updated_at": "2026-11-15T22:00:00+08:00",
        },
        {
            "building_id": "bldg_a1",
            "student_id": "stu_synth_0002",
            "service_date": NIGHT_TEXT,
            "planned_return_at": "2026-11-16T01:00:00+08:00",
            "status": "ACTIVE",
            "version": 1,
            "updated_at": "2026-11-15T22:30:00+08:00",
        },
        # 次夜申请：24:00 之后仍可提交，绝不能混进当夜名单。
        {
            "building_id": "bldg_a1",
            "student_id": "stu_synth_0003",
            "service_date": (NIGHT + timedelta(days=1)).isoformat(),
            "planned_return_at": "2026-11-17T00:40:00+08:00",
            "status": "ACTIVE",
            "version": 1,
            "updated_at": "2026-11-16T00:10:00+08:00",
        },
    ]
    enqueued = _install_a_stubs(monkeypatch, reservations)

    delete = text("DELETE FROM building_list_snapshots WHERE building_id=:b AND service_date=:d")
    params = {"b": "bldg_a1", "d": NIGHT}
    with get_engine().begin() as conn:
        conn.execute(delete, params)
    try:
        assert building_list.run_snapshot("bldg_a1", NIGHT) == 2
        assert enqueued == [("dorm.list.summary", ["usr_synth_0003"], f"dorm:bldg_a1:{NIGHT_TEXT}:SUMMARY")]

        # 00:20 学生改期、另一人撤销。
        reservations[0].update(planned_return_at="2026-11-16T02:10:00+08:00", version=2)
        reservations[1].update(status="CANCELLED", version=2)
        payload = building_list.tonight("bldg_a1", datetime(2026, 11, 16, 0, 20, tzinfo=TZ))

        assert payload["service_date"] == NIGHT_TEXT
        assert payload["summary_generated_at"] == "2026-11-16T00:00:00+08:00"
        assert [item["student_id"] for item in payload["items"]] == ["stu_synth_0001", "stu_synth_0002"]
        flags = {item["student_id"]: item["change_flag"] for item in payload["items"]}
        assert flags == {"stu_synth_0001": "RESCHEDULED", "stu_synth_0002": "CANCELLED"}
    finally:
        with get_engine().begin() as conn:
            conn.execute(delete, params)


def _purge_returns(*student_ids: str) -> None:
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        for student_id in student_ids:
            conn.execute(
                text("DELETE FROM return_records WHERE student_id = :s"), {"s": student_id}
            )


def _reservation_row(student_id: str, service_date: date, **changes) -> dict:
    base = {
        "building_id": "bldg_a1",
        "student_id": student_id,
        "service_date": service_date.isoformat(),
        "planned_return_at": "2026-11-16T00:40:00+08:00",
        "status": "ACTIVE",
        "version": 1,
        "updated_at": "2026-11-15T22:00:00+08:00",
    }
    return {**base, **changes}


def test_the_list_rolls_to_the_next_night_at_six(client, monkeypatch) -> None:
    """需求（h）：06:00 一到名单自动切次夜，前一晚的情况不再留在本页。"""
    from app.modules.building_list import service as building_list

    next_night = NIGHT + timedelta(days=1)
    _install_a_stubs(
        monkeypatch,
        [
            _reservation_row("stu_synth_0001", NIGHT),
            _reservation_row("stu_synth_0002", next_night),
        ],
    )
    _purge_returns("stu_synth_0001", "stu_synth_0002")

    before = building_list.tonight("bldg_a1", datetime(2026, 11, 16, 5, 59, tzinfo=TZ))
    assert before["service_date"] == NIGHT_TEXT
    assert [item["student_id"] for item in before["items"]] == ["stu_synth_0001"]

    after = building_list.tonight("bldg_a1", datetime(2026, 11, 16, 6, 0, tzinfo=TZ))
    assert after["service_date"] == next_night.isoformat()
    assert [item["student_id"] for item in after["items"]] == ["stu_synth_0002"]


def test_the_qr_passage_shows_in_the_list_and_pushes_nothing(client, monkeypatch) -> None:
    """需求（g）：扫码通行同步进阿姨汇总单，但通行本身不推送任何消息。"""
    from app.core.db import get_engine
    from app.modules.building_list import service as building_list
    from app.modules.returns import service as returns

    enqueued = _install_a_stubs(monkeypatch, [_reservation_row("stu_synth_0001", NIGHT)])
    _purge_returns("stu_synth_0001")
    try:
        with get_engine().begin() as conn:
            returns.confirm_return(
                conn,
                student_id="stu_synth_0001",
                service_date=NIGHT,
                source=returns.SOURCE_QR,
                evidence={"device_id": "dev_synth_a1_01", "pass_id": "pass_synth_test_0001"},
                occurred_at=datetime(2026, 11, 16, 0, 41, tzinfo=TZ),
                idempotency_key="test:qr:pass_synth_test_0001",
                gate_id="gate_a1_north",
            )

        payload = building_list.tonight("bldg_a1", datetime(2026, 11, 16, 0, 45, tzinfo=TZ))
        assert payload["counters"] == {"total": 1, "entered": 1}
        item = payload["items"][0]
        assert item["return_status"] == "ENTERED"
        assert item["entered_at"] == "2026-11-16T00:41:00+08:00"
        assert item["gate_id"] == "gate_a1_north"
        assert item["return_source"] == "QR"
        # 通行只是读展示：不产生任何推送。
        assert enqueued == []
    finally:
        _purge_returns("stu_synth_0001")
