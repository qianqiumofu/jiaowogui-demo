"""园区端值班授权：每栋楼夜晚的阿姨是固定的，园区端逐夜只登记代班。

对应需求「每栋楼的夜晚值班阿姨是固定的，值班授权中可以只设定代班选项」与规则 R11、docs/08：
- 固定值守在 `building_duty_roster`：一栋可以并排白班与夜班两位，一人也可以管多栋，登记一次长期生效；
- 代班在 `duty_assignments`：按夜追加（`POST /duty-assignments/switch`），只在那一夜的班次窗口内生效；
- 阿姨的可见楼栋 = 名册固定班 ∪ 当夜代班 ∪ 园区建号时绑的楼栋，由 `identity.resolve_scope` 现算；
  名册卸任会顺带解掉那条账号绑定，否则「名册删了人、她照样进得来今晚名单」；
- 名册事实另有一条查询：`duty.fixed_watch_buildings` 只认固定值守、不认代班，不替代业务权限，
  固定名册查询走 `directory.get_fixed_watch_staff`；
- 写入都会把该楼栋那一夜排进 24:00 汇总队列。
"""

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.db import get_engine
from tests.conftest import API, auth, jump_clock, token_for

pytestmark = pytest.mark.usefixtures("seeded_demo_db")

TZ = ZoneInfo("Asia/Shanghai")
# 演示库只有一个工号账号：王宿管固定主值 bldg_a1，可登录 `dorm`。
DEMO_STAFF = "usr_synth_0003"
# 第二位固定负责人借这个账户占位——名册只认「人在 `users` 里」，本文件不碰收件人派生。
OTHER_STAFF = "usr_synth_0005"
COUNSELOR = "usr_synth_0002"  # 没有任何固定值守楼栋，用来验代班前提
A1 = "bldg_a1"
A2 = "bldg_a2"  # 种子给她 23:00 起的代班楼栋
A3 = "bldg_a3"
TARGET = "bldg_a4"  # 本文件的改派目标：不在种子代班与快照里

_ROSTER_COLUMNS = (
    "roster_id",
    "building_id",
    "staff_user_id",
    "shift_start",
    "shift_end",
    "valid_from",
    "valid_to",
    "created_at",
    "updated_at",
)


def _night_of(moment: datetime) -> date:
    return (moment - timedelta(hours=6)).date()


def _window(night: date) -> dict[str, str]:
    """整夜窗口 [D 06:00, D+1 06:00)：代班不给窗口时就是这个。"""
    return {
        "shift_start": f"{night.isoformat()}T06:00:00+08:00",
        "shift_end": f"{(night + timedelta(days=1)).isoformat()}T06:00:00+08:00",
    }


def backup_roster() -> list[dict]:
    """整表搬走固定班：本文件的用例会登记与卸任名册行，逐楼栋还原容易漏。"""
    with get_engine().connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(f"SELECT {', '.join(_ROSTER_COLUMNS)} FROM building_duty_roster")
            ).mappings().all()
        ]


def restore_roster(backup: list[dict]) -> None:
    insert = text(
        "INSERT INTO building_duty_roster "
        f"({', '.join(_ROSTER_COLUMNS)}) "
        "VALUES (:" + ", :".join(_ROSTER_COLUMNS) + ")"
    )
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM building_duty_roster"))
        for row in backup:
            conn.execute(insert, row)


def backup_account_binding() -> list[str]:
    """园区建号时绑的楼栋（A 侧 `users.building_ids`）：卸任名册会顺带解绑，用例后得放回去。"""
    with get_engine().connect() as conn:
        raw = (
            conn.execute(
                text("SELECT building_ids FROM users WHERE user_id = :u"), {"u": DEMO_STAFF}
            )
            .scalars()
            .first()
        )
    return list(json.loads(raw) if isinstance(raw, str) else raw or [])


def restore_account_binding(building_ids: list[str]) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE users SET building_ids = CAST(:ids AS JSON) WHERE user_id = :u"),
            {"ids": json.dumps(building_ids), "u": DEMO_STAFF},
        )


def purge_duty_rows(building_ids: list[str]) -> None:
    keys = " OR ".join(
        f"business_key LIKE 'DORM_TONIGHT_SNAPSHOT:{bid}:%'" for bid in building_ids
    )
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM duty_assignments WHERE building_id = ANY(:ids)"),
            {"ids": building_ids},
        )
        conn.execute(text(f"DELETE FROM background_jobs WHERE {keys}"))


@pytest.fixture(autouse=True)
def pristine_duty(client):
    """演示库与测试共用：用例前后各还原一遍固定班与账号绑定，代班与汇总任务按楼栋收干净。

    前置也要清 A3/TARGET：本文件的用例直接插代班行做「代班不进风险」这类事实，
    单跑或中断后残留的同号行会让下一次撞主键。种子在这两栋没有代班行，清掉不影响别的用例。
    """
    roster = backup_roster()
    binding = backup_account_binding()
    purge_duty_rows([A3, TARGET])
    yield
    purge_duty_rows([A3, TARGET])
    restore_roster(roster)
    restore_account_binding(binding)


def _scope(client, login: str) -> dict:
    return client.get(f"{API}/me", headers=auth(token_for(client, login))).json()["scope"]


def _roster(client, token: str, **params) -> list[dict]:
    response = client.get(f"{API}/duty-roster", params=params, headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _set_roster(client, token: str, **changes) -> dict:
    payload = {"building_id": TARGET, "staff_user_id": OTHER_STAFF, **changes}
    response = client.post(f"{API}/duty-roster", json=payload, headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def _revoke_roster(client, token: str, building_id: str, staff_user_id: str):
    return client.post(
        f"{API}/duty-roster/revoke",
        json={"building_id": building_id, "staff_user_id": staff_user_id},
        headers=auth(token),
    )


def _switch(client, token: str, night: date, **changes) -> dict:
    payload = {
        "staff_user_id": DEMO_STAFF,
        "building_id": TARGET,
        "service_date": night.isoformat(),
        **_window(night),
        **changes,
    }
    response = client.post(f"{API}/duty-assignments/switch", json=payload, headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def test_fixed_guardian_needs_no_nightly_grant(client) -> None:
    """阿姨每晚的楼栋由固定班给，园区端不需要再逐夜点一次「主值授权」。"""
    jump_clock(client, 20)
    token = token_for(client, "dorm")

    scope = _scope(client, "dorm")
    assert scope["building_ids"] == [A1]
    assert "ALL_AUTHORIZED" not in str(scope)

    rows = _roster(client, token, staff_user_id=DEMO_STAFF)
    # 展示名跟着 107 栋真实目录走（东1 号楼），building_id 与 code 仍是 bldg_a1/A1：
    # 名册页面读的是展示名，测试与门牌锚的是那两串（docs/10）。
    assert [row["building_name"] for row in rows] == ["东1 号楼"]
    assert rows[0]["shift_start"] == "18:00" and rows[0]["shift_end"] == "06:00"
    assert rows[0]["covers_tonight"] is True
    assert rows[0]["on_duty_now"] is True


def test_roster_window_is_a_repeating_clock_time(client) -> None:
    """固定班的窗口是「每晚几点到几点」，跨零点按回绕判定，不是某个时间戳。"""
    token = token_for(client, "campus")
    at = jump_clock(client, 19)
    night = _night_of(at)
    row = _set_roster(client, token, shift_start="20:00", shift_end="06:00")
    assert row["valid_from"] == night.isoformat(), "缺省生效日就是今晚所在的那个业务夜"
    assert row["on_duty_now"] is False, "19:00 还没到 20:00 上岗"

    jump_clock(client, 21)
    rows = _roster(client, token, building_id=TARGET)
    assert [(r["staff_user_id"], r["on_duty_now"]) for r in rows] == [(OTHER_STAFF, True)]


def test_roster_adds_a_building_and_revoke_takes_it_back(client) -> None:
    """登记是追加、卸任指到人：一栋可以并排两位，删掉哪一行当场交出哪一栋。"""
    jump_clock(client, 20)
    token = token_for(client, "campus")

    moved = _set_roster(client, token, staff_user_id=DEMO_STAFF)
    assert moved["building_id"] == TARGET
    assert _roster(client, token, staff_user_id=DEMO_STAFF) != [], "她原来那栋还在"
    assert sorted(_scope(client, "dorm")["building_ids"]) == sorted([A1, TARGET])

    revoked = _revoke_roster(client, token, TARGET, DEMO_STAFF)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["building_id"] == TARGET
    assert _scope(client, "dorm")["building_ids"] == [A1], "卸任的瞬间范围就收回"

    again = _revoke_roster(client, token, TARGET, DEMO_STAFF)
    assert again.status_code == 404, again.text
    assert again.json()["code"] == "DUTY_ROSTER_NOT_FOUND"


def test_revoke_roster_also_unbinds_the_staff_account(client) -> None:
    """名册卸任要连带解开工号账号上那条绑楼：否则删了名册行，阿姨照样进得来今晚名单。

    这是园区端的两条授权口子（名册 / 建号绑楼）里唯一会互相收敛的一条，反方向不成立——
    只绑了账号的人不会自动进名册。见《给A-值班授权改由园区端签发-需评审.md》。
    """
    jump_clock(client, 20)
    token = token_for(client, "campus")
    assert _scope(client, "dorm")["building_ids"] == [A1]

    assert _revoke_roster(client, token, A1, DEMO_STAFF).status_code == 200
    assert _scope(client, "dorm")["building_ids"] == [], "两条口子一起收，范围才是真的没了"

    accounts = client.get(f"{API}/staff-accounts", headers=auth(token)).json()["items"]
    binding = next(item["building_ids"] for item in accounts if item["id"] == DEMO_STAFF)
    assert A1 not in binding


def test_reassign_queues_that_buildings_nightly_summary(client) -> None:
    at = jump_clock(client, 20)
    night = _night_of(at)
    _set_roster(client, token_for(client, "campus"))
    with get_engine().connect() as conn:
        job = conn.execute(
            text("SELECT job_type, status FROM background_jobs WHERE business_key = :key"),
            {"key": f"DORM_TONIGHT_SNAPSHOT:{TARGET}:{night.isoformat()}"},
        ).mappings().first()
    assert job is not None, "有了固定负责人，那一夜就得等得到晚归单"
    assert (job["job_type"], job["status"]) == ("DORM_TONIGHT_SNAPSHOT", "PENDING")


def test_substitute_does_not_require_an_existing_fixed_building(client) -> None:
    """沿用已确认基线：无需先有固定主值即可登记代班。"""
    at = jump_clock(client, 20)
    night = _night_of(at)
    response = client.post(
        f"{API}/duty-assignments/switch",
        json={
            "staff_user_id": COUNSELOR,
            "building_id": TARGET,
            "service_date": night.isoformat(),
        },
        headers=auth(token_for(client, "campus")),
    )
    assert response.status_code == 200, response.text
    assert response.json()["staff_user_id"] == COUNSELOR
    assert response.json()["is_substitute"] is True


def test_substitute_on_fixed_building_preserves_existing_authorization(client) -> None:
    """额外班次不撤销原固定授权；与原基线兼容。"""
    at = jump_clock(client, 20)
    night = _night_of(at)
    token = token_for(client, "campus")
    _set_roster(client, token)

    response = client.post(
        f"{API}/duty-assignments/switch",
        json={
            "staff_user_id": OTHER_STAFF,
            "building_id": TARGET,
            "service_date": night.isoformat(),
        },
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_substitute"] is True


def test_substitute_extends_only_that_night_and_replay_is_rejected(client) -> None:
    at = jump_clock(client, 20)
    night = _night_of(at)
    token = token_for(client, "campus")
    substitute = _switch(client, token, night)
    assert substitute["is_substitute"] is True
    assert substitute["shift_state"] == "ACTIVE"

    assert sorted(_scope(client, "dorm")["building_ids"]) == sorted([A1, TARGET])

    with get_engine().connect() as conn:
        nights = conn.execute(
            text("SELECT service_date FROM duty_assignments WHERE building_id = :b"), {"b": TARGET}
        ).scalars().all()
    assert list(nights) == [night], "代班只落在登记的那一夜"

    again = client.post(
        f"{API}/duty-assignments/switch",
        json={
            "staff_user_id": DEMO_STAFF,
            "building_id": TARGET,
            "service_date": night.isoformat(),
            **_window(night),
        },
        headers=auth(token),
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "DUTY_SLOT_TAKEN"

    revoked = client.delete(
        f"{API}/duty-assignments/{substitute['duty_id']}", headers=auth(token)
    )
    assert revoked.status_code == 200, revoked.text
    assert _scope(client, "dorm")["building_ids"] == [A1]


def test_substitute_scope_only_within_its_shift(client) -> None:
    """代班是按夜的临时追加：23:00 那班开始之前，隔壁那栋她打不开（固定那半整夜都在）。"""
    jump_clock(client, 22, 30)
    assert _scope(client, "dorm")["building_ids"] == [A1]
    jump_clock(client, 23, 30)
    assert sorted(_scope(client, "dorm")["building_ids"]) == [A1, A2]


def test_substitute_window_must_stay_inside_the_business_night(client) -> None:
    token = token_for(client, "campus")
    night = date(2027, 3, 2)
    _, end = _window(night).values()

    straddling = client.post(
        f"{API}/duty-assignments/switch",
        json={
            "staff_user_id": DEMO_STAFF,
            "building_id": TARGET,
            "service_date": night.isoformat(),
            "shift_start": f"{night.isoformat()}T05:00:00+08:00",
            "shift_end": end,
        },
        headers=auth(token),
    )
    assert straddling.status_code == 422, straddling.text
    assert straddling.json()["details"]["service_date"] == night.isoformat()

    naive = client.post(
        f"{API}/duty-assignments/switch",
        json={
            "staff_user_id": DEMO_STAFF,
            "building_id": TARGET,
            "service_date": night.isoformat(),
            "shift_start": f"{night.isoformat()}T08:00:00",
        },
        headers=auth(token),
    )
    assert naive.status_code == 422, naive.text
    assert naive.json()["details"]["field"] == "shift_start"


def test_roster_and_substitute_validate_the_subject(client) -> None:
    token = token_for(client, "campus")
    night = date(2027, 3, 3)

    unknown_staff = client.post(
        f"{API}/duty-roster",
        json={"building_id": TARGET, "staff_user_id": "usr_does_not_exist"},
        headers=auth(token),
    )
    assert unknown_staff.status_code == 422, unknown_staff.text
    assert unknown_staff.json()["details"]["field"] == "staff_user_id"

    unknown_building = client.post(
        f"{API}/duty-assignments/switch",
        json={
            "staff_user_id": DEMO_STAFF,
            "building_id": "bldg_does_not_exist",
            "service_date": night.isoformat(),
        },
        headers=auth(token),
    )
    assert unknown_building.status_code == 422, unknown_building.text
    assert unknown_building.json()["details"]["field"] == "building_id"

    same_clock = client.post(
        f"{API}/duty-roster",
        json={
            "building_id": TARGET,
            "staff_user_id": OTHER_STAFF,
            "shift_start": "18:00",
            "shift_end": "18:00",
        },
        headers=auth(token),
    )
    assert same_clock.status_code == 422, same_clock.text
    assert same_clock.json()["details"]["shift_end"] == "18:00"

    bad_clock = client.post(
        f"{API}/duty-roster",
        json={"building_id": TARGET, "staff_user_id": OTHER_STAFF, "shift_start": "25:00"},
        headers=auth(token),
    )
    assert bad_clock.status_code == 422, bad_clock.text
    assert bad_clock.json()["details"]["field"] == "shift_start"

    bad_range = client.post(
        f"{API}/duty-roster",
        json={
            "building_id": TARGET,
            "staff_user_id": OTHER_STAFF,
            "valid_from": night.isoformat(),
            "valid_to": night.isoformat(),
        },
        headers=auth(token),
    )
    assert bad_range.status_code == 422, bad_range.text
    assert bad_range.json()["details"]["valid_to"] == night.isoformat()


def test_only_campus_may_write_duty(client) -> None:
    payload = {"building_id": TARGET, "staff_user_id": DEMO_STAFF, "service_date": "2027-03-01"}
    posts = (
        "/duty-roster",
        "/duty-roster/revoke",
        "/duty-assignments",
        "/duty-assignments/switch",
    )
    for login in ("dorm", "counselor", "student"):
        token = token_for(client, login)
        for path in posts:
            response = client.post(f"{API}{path}", json=payload, headers=auth(token))
            assert response.status_code == 403, (login, path, response.text)
            assert response.json()["code"] == "FORBIDDEN_ACTION"
            assert response.json()["details"]["action"].startswith("duty:")

        removed = client.delete(f"{API}/duty-assignments/duty_none", headers=auth(token))
        assert removed.status_code == 403, (login, removed.text)
        assert removed.json()["details"]["action"].startswith("duty:")


def test_duty_lists_are_narrowed_to_the_current_user(client) -> None:
    """园区看全校，阿姨只看自己那一身；固定班与代班两张名单同一道收窄。"""
    at = jump_clock(client, 20)
    night = _night_of(at)
    token = token_for(client, "campus")
    substitute = _switch(client, token, night)

    dorm_view = client.get(
        f"{API}/duty-assignments",
        params={"staff_user_id": COUNSELOR},
        headers=auth(token_for(client, "dorm")),
    )
    assert dorm_view.status_code == 200
    items = dorm_view.json()["items"]
    assert items and all(item["staff_user_id"] == DEMO_STAFF for item in items), "不接受客户端传别人"
    assert substitute["duty_id"] in {item["duty_id"] for item in items}
    by_id = {item["duty_id"]: item for item in items}
    assert by_id[f"duty_a2_{night}"]["shift_state"] == "SCHEDULED", "种子的代班 23:00 才开始"
    assert by_id[substitute["duty_id"]]["shift_state"] == "ACTIVE"

    dorm_roster = client.get(f"{API}/duty-roster", headers=auth(token_for(client, "dorm")))
    assert dorm_roster.status_code == 200
    assert {row["building_id"] for row in dorm_roster.json()["items"]} == {A1}

    filtered = client.get(
        f"{API}/duty-assignments",
        params={"building_id": TARGET, "service_date": night.isoformat()},
        headers=auth(token),
    ).json()["items"]
    assert [item["duty_id"] for item in filtered] == [substitute["duty_id"]]
    assert filtered[0]["building_name"] and filtered[0]["park_name"]

    counselor = client.get(f"{API}/duty-assignments", headers=auth(token_for(client, "counselor")))
    assert counselor.status_code == 200
    assert counselor.json()["items"] == []


def test_night_roster_lists_the_fixed_guardian_before_the_substitute(client) -> None:
    """晚归单的一行要同时给出固定负责人与当夜代班，固定在前。"""
    from app.modules.duty import service as duty

    at = jump_clock(client, 20)
    night = _night_of(at)
    token = token_for(client, "campus")
    _set_roster(client, token)
    _switch(client, token, night)

    people = duty.night_duty_map(night)[TARGET]
    names = [(person["display_name"], person["is_substitute"]) for person in people]
    assert len(names) == 2, names
    assert [substitute for _name, substitute in names] == [False, True], "固定在前、代班在后"
    assert names[1] == ("王宿管", True)

    # 固定班落到这一夜的具体时刻：18:00—次日 06:00，结束不能跑到开始之前。
    fixed = people[0]
    assert fixed["shift_start"] == f"{night.isoformat()}T18:00:00+08:00"
    assert fixed["shift_end"] == f"{(night + timedelta(days=1)).isoformat()}T06:00:00+08:00"
    assert fixed["shift_start"] < fixed["shift_end"]


def _insert_substitute(duty_id: str, staff_user_id: str, building_id: str, night: date) -> None:
    """直接写一条代班行：接口不许回填历史夜，「代班不进风险范围」这条也只能这样造。"""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO duty_assignments (duty_id, staff_user_id, building_id, service_date, "
                "shift_start, shift_end, is_substitute) "
                "VALUES (:duty_id, :staff_user_id, :building_id, :service_date, "
                ":shift_start, :shift_end, true)"
            ),
            {
                "duty_id": duty_id,
                "staff_user_id": staff_user_id,
                "building_id": building_id,
                "service_date": night,
                "shift_start": datetime.combine(night, time(23, 0), tzinfo=TZ),
                "shift_end": datetime.combine(night + timedelta(days=1), time(6, 0), tzinfo=TZ),
            },
        )


def test_fixed_roster_scope_ignores_substitute_assignments(client) -> None:
    """名册查询只返回固定关系；业务范围仍含有效代班。"""
    from app.modules.duty import service as duty

    night = _night_of(jump_clock(client, 20))
    at = datetime.combine(night, time(23, 30), tzinfo=TZ)

    assert duty.fixed_watch_buildings(DEMO_STAFF, at) == [A1]
    _insert_substitute("duty_watch_recent", DEMO_STAFF, A3, night)
    _insert_substitute("duty_watch_stale", DEMO_STAFF, TARGET, night - timedelta(days=9))
    _insert_substitute("duty_watch_future", DEMO_STAFF, A3, night + timedelta(days=1))
    assert duty.fixed_watch_buildings(DEMO_STAFF, at) == [A1], "当夜代班、老代班、未来代班都不进风险范围"
    assert duty.on_duty_buildings(DEMO_STAFF, at) == sorted(
        {A1, A2, A3}
    ), "名单范围照旧把当夜代班算进来"


def test_fixed_roster_scope_survives_the_shift_window(client) -> None:
    """固定值守那一栋整夜都在：白天补录、18:00 上岗前、凌晨交班后都照样能跟进本楼学生。"""
    from app.modules.duty import service as duty

    night = _night_of(jump_clock(client, 20))
    before_shift = datetime.combine(night, time(17, 30), tzinfo=TZ)
    after_dawn = datetime.combine(night + timedelta(days=1), time(5, 30), tzinfo=TZ)

    assert duty.fixed_watch_buildings(DEMO_STAFF, before_shift) == [A1]
    assert duty.fixed_watch_buildings(DEMO_STAFF, after_dawn) == [A1], "同一夜内班次开合不该改变主值范围"


def test_fixed_roster_scope_follows_the_reassignment(client) -> None:
    """登记与卸任之后范围当场跟着走：接手的那栋立刻能看到本楼仍 OPEN 的事件，前任当场交出。"""
    from app.modules.duty import service as duty

    night = _night_of(jump_clock(client, 20))
    at = datetime.combine(night, time(17, 30), tzinfo=TZ)
    assert duty.fixed_watch_buildings(DEMO_STAFF, at) == [A1]

    _set_roster(client, token_for(client, "campus"), staff_user_id=DEMO_STAFF)
    assert duty.fixed_watch_buildings(DEMO_STAFF, at) == sorted([A1, TARGET])

    assert duty.fixed_watch_buildings("usr_synth_0004", at) == [], "没有名册记录就没有固定楼栋"


def test_fixed_roster_recipients_follow_the_watch_scope(client) -> None:
    """固定名册人员查询不含代班；业务收件与权限仍使用 get_duty_staff。

    只验证两个领域查询的区别，不改风险已确认的权限。
    今晚名单与 24:00 汇总照旧用含代班的 `get_duty_staff`，两条口径别互相顶替。
    """
    from app.modules.directory import service as directory
    from app.modules.duty import service as duty

    night = _night_of(jump_clock(client, 20))
    at = datetime.combine(night, time(23, 30), tzinfo=TZ)
    _insert_substitute("duty_watch_recipients", DEMO_STAFF, A3, night)

    assert DEMO_STAFF in directory.get_duty_staff(A3, at), "名单口径照旧把当夜代班算成当班人"
    assert directory.get_fixed_watch_staff(A3, at) == [], "代班楼栋不进风险收件人"

    noon = datetime.combine(night, time(13, 0), tzinfo=TZ)
    dawn = datetime.combine(night + timedelta(days=1), time(5, 30), tzinfo=TZ)
    for moment in (at, noon, dawn):
        recipients = directory.get_fixed_watch_staff(A1, moment)
        assert recipients == [DEMO_STAFF], "主值那栋全天候收风险，交班前后都一样"
        for staff_user_id in recipients:
            assert A1 in duty.fixed_watch_buildings(staff_user_id, moment), "收件人必须打得开这栋楼的事件"


def test_revoke_failure_rolls_back_roster_binding_and_audit(client, monkeypatch):
    """跨模块解绑中途失败不能留下半次撤权，真实 PostgreSQL 验证。"""
    from app.modules.identity import staff_accounts
    from app.modules.duty import service as duty

    at = jump_clock(client, 20)
    bound_before = backup_account_binding()
    with get_engine().connect() as conn:
        audits_before = conn.execute(text("SELECT count(*) FROM audit_logs WHERE action='DUTY_ROSTER_REVOKED'")).scalar_one()
    remove = staff_accounts.remove_building_binding

    def fail_after_unbinding(session, account_id, building_id):
        remove(session, account_id, building_id)
        session.flush()
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(staff_accounts, "remove_building_binding", fail_after_unbinding)
    with pytest.raises(RuntimeError, match="synthetic transaction failure"):
        duty.revoke_roster({"building_id": A1, "staff_user_id": DEMO_STAFF}, at, actor_user_id="usr_synth_0004")
    assert duty.load_roster(A1, at, staff_user_id=DEMO_STAFF) is not None
    assert backup_account_binding() == bound_before
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_logs WHERE action='DUTY_ROSTER_REVOKED'")).scalar_one() == audits_before


@pytest.mark.parametrize("value", ["18", "18:00:00", "18:00+08:00", "18:00:00.123"])
def test_roster_clock_rejects_non_contract_formats(client, value):
    response = client.post(f"{API}/duty-roster", headers=auth(token_for(client, "campus")), json={
        "building_id": TARGET, "staff_user_id": DEMO_STAFF, "shift_start": value})
    assert response.status_code == 422, response.text
    assert response.json()["details"]["field"] == "shift_start"


@pytest.mark.parametrize("start,end,expected_start,expected_end", [
    ("20:00", "08:00", "2026-11-15T20:00:00+08:00", "2026-11-16T08:00:00+08:00"),
    ("05:00", "04:00", "2026-11-16T05:00:00+08:00", "2026-11-17T04:00:00+08:00"),
    ("06:00", "18:00", "2026-11-15T06:00:00+08:00", "2026-11-15T18:00:00+08:00"),
])
def test_repeating_windows_remain_ordered_across_dawn(client, start, end, expected_start, expected_end):
    from app.modules.duty import service as duty
    jump_clock(client, 20)
    _set_roster(client, token_for(client, "campus"), shift_start=start, shift_end=end)
    row = duty.night_roster(TARGET, date(2026, 11, 15))[0]
    assert row["shift_start"] == expected_start
    assert row["shift_end"] == expected_end


def test_concurrent_roster_revoke_is_atomic_and_only_one_wins(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.core.errors import ApiError
    from app.modules.duty import service as duty
    at = jump_clock(client, 20)
    _set_roster(client, token_for(client, "campus"), staff_user_id=DEMO_STAFF)
    gate = Barrier(2)

    def remove():
        gate.wait(timeout=5)
        try:
            duty.revoke_roster({"building_id": TARGET, "staff_user_id": DEMO_STAFF}, at,
                               actor_user_id="usr_synth_0004")
            return 200
        except ApiError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: remove(), range(2)))
    assert sorted(outcomes) == [200, 404]
    assert duty.load_roster(TARGET, at, staff_user_id=DEMO_STAFF) is None
