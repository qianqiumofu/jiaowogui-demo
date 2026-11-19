"""园区端全校晚归统计：三值口径、五个筛选维度、快照归属、越权与降级。

对应基线 R14 与「园区统计口径」（人数/晚归夜数/返宿次数分列、发生时快照归属、
取消与领码不计实际晚归、预约源未落地时降级为 null + data_gaps）。
日期锚在演示夜之前的历史区间，取决于 `python -m app.db.seed --service-date 2026-11-15`
（见 docs/10-演示数据与账号.md：演示夜之前 14 夜）。
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.db import get_engine
from tests.conftest import API, auth, token_for

DATE_FROM = "2026-11-01"
DATE_TO = "2026-11-14"
RANGE = {"date_from": DATE_FROM, "date_to": DATE_TO}
HISTORY_NIGHTS = 14


pytestmark = pytest.mark.usefixtures("seeded_demo_db")

def _campus(client):
    return auth(token_for(client, "campus"))


def _statistics(client, headers, **params) -> dict:
    response = client.get(f"{API}/statistics", headers=headers, params={**RANGE, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_three_metrics_are_split_and_nights_are_unique_per_student(client) -> None:
    """三值分列：合成历史里一名学生一夜只记一次，所以晚归夜数恒等于返宿次数。

    夜数按「学生 × 业务夜」去重，完全可以大于人数（一人多夜）；只有人数是不去重就会虚增的那个。
    """
    totals = _statistics(client, _campus(client), group_by="none")["totals"]
    assert 0 < totals["people"] <= min(totals["nights"], totals["enrolled"])
    assert totals["nights"] == totals["returns"]
    # 次数按来源拆开，两列相加等于总次数。
    assert totals["qr_returns"] + totals["manual_returns"] == totals["returns"]
    assert totals["enrolled"] == _statistics(client, _campus(client))["totals"]["enrolled"]


def test_return_source_filter_keeps_the_enrolled_denominator(client) -> None:
    """筛「返宿来源」只改变事实行，在册名册不带来源：分母被清零过一次，这条锁住回归。"""
    everything = _statistics(client, _campus(client))["totals"]
    for source in ("QR", "MANUAL"):
        filtered = _statistics(client, _campus(client), return_source=source)["totals"]
        assert filtered["enrolled"] == everything["enrolled"]
        assert filtered["returns"] > 0
        assert filtered[f"{'qr' if source == 'QR' else 'manual'}_returns"] == filtered["returns"]
        assert filtered[f"{'manual' if source == 'QR' else 'qr'}_returns"] == 0
    parts = [
        _statistics(client, _campus(client), return_source=source)["totals"]
        for source in ("QR", "MANUAL")
    ]
    assert parts[0]["nights"] + parts[1]["nights"] == everything["nights"]


@pytest.mark.parametrize("dimension", ["park", "college", "building", "grade", "gender"])
def test_each_dimension_partitions_the_same_facts(client, dimension: str) -> None:
    """任一分组维度都要盖住全部事实：组内夜数相加等于总计，且没有组外键值。"""
    body = _statistics(client, _campus(client), group_by=dimension)
    rows = body["rows"]
    assert rows, body
    assert sum(row["nights"] for row in rows) == body["totals"]["nights"]
    assert sum(row["returns"] for row in rows) == body["totals"]["returns"]
    assert all(row["value"] and row["label"] for row in rows)
    # 组内人数不可能超过去重后的总人数，晚归夜数则按组独立。
    assert all(row["people"] <= body["totals"]["people"] for row in rows)
    if dimension == "gender":
        assert {row["value"] for row in rows} == {"MALE", "FEMALE"}
        assert {row["label"] for row in rows} == {"男生", "女生"}
    if dimension == "grade":
        assert {row["value"] for row in rows} <= {"2023", "2024", "2025"}


def test_park_and_building_are_two_levels_of_the_same_dimension(client) -> None:
    """片区与楼栋是同一套归属的两级：楼栋行能经筛选器换算到片区行。"""
    options = client.get(f"{API}/statistics/filters", headers=_campus(client))
    assert options.status_code == 200, options.text
    filters = options.json()
    park_of = {row["building_id"]: row["park_org_id"] for row in filters["buildings"]}
    assert len(filters["parks"]) == 9
    assert sum(row["building_count"] for row in filters["parks"]) == len(filters["buildings"])

    by_building = _statistics(client, _campus(client), group_by="building")["rows"]
    by_park = {row["value"]: row["nights"] for row in _statistics(client, _campus(client))["rows"]}
    nights_by_park: dict[str, int] = {}
    for row in by_building:
        nights_by_park[park_of[row["value"]]] = nights_by_park.get(park_of[row["value"]], 0) + row["nights"]
    assert nights_by_park == by_park


def test_filter_values_narrow_to_rows_of_that_value(client) -> None:
    """单项筛选与分组结果自洽：筛片区后只剩该片区的楼栋，筛性别后只剩该性别。"""
    one_park = _statistics(client, _campus(client))["rows"][0]["value"]
    options = client.get(f"{API}/statistics/filters", headers=_campus(client)).json()
    park_buildings = {
        row["building_id"] for row in options["buildings"] if row["park_org_id"] == one_park
    }
    rows = _statistics(client, _campus(client), park_org_id=one_park, group_by="building")["rows"]
    assert {row["value"] for row in rows} <= park_buildings
    assert all(row["people"] <= row["enrolled"] for row in rows)

    for row in _statistics(client, _campus(client), gender="FEMALE", group_by="gender")["rows"]:
        assert row["value"] == "FEMALE"


def test_attribution_snapshot_and_current_differ_after_a_move(client) -> None:
    """发生过搬迁时，快照口径按当晚楼栋归属，current 口径按当前在册楼栋归属。"""
    with get_engine().connect() as conn:
        moved = conn.execute(
            text(
                """
                SELECT rr.student_id, rr.service_date, res.building_id
                FROM return_records rr
                JOIN residences res ON res.student_id = rr.student_id AND res.valid_to IS NULL
                WHERE res.building_id = 'bldg_a3'
                  AND rr.service_date BETWEEN :date_from AND :date_to
                ORDER BY rr.service_date DESC
                LIMIT 1
                """
            ),
            {"date_from": DATE_FROM, "date_to": DATE_TO},
        ).mappings().first()
    if moved is None:
        pytest.fail("合成历史里 A3 没有晚归记录，请按 docs/10 用 --service-date 2026-11-15 重新 seed。")
    student, night = moved["student_id"], moved["service_date"]
    single = {"date_from": night.isoformat(), "date_to": night.isoformat()}

    # A3（男生，西一区）搬到同样为男生的 A5（西三区），生效日在当晚之后。
    moves_in = night + timedelta(days=1)
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE residences SET valid_to = :valid_to WHERE student_id = :s AND valid_to IS NULL"),
            {"s": student, "valid_to": moves_in},
        )
        conn.execute(
            text(
                """
                INSERT INTO residences (residence_id, student_id, building_id, room_no, valid_from)
                VALUES ('res_test_statistics_move', :s, 'bldg_a5', 'A5-999', :valid_from)
                """
            ),
            {"s": student, "valid_from": moves_in},
        )
    try:
        options = client.get(f"{API}/statistics/filters", headers=_campus(client)).json()
        park_of = {row["building_id"]: row["park_org_id"] for row in options["buildings"]}
        west1, west3 = park_of["bldg_a3"], park_of["bldg_a5"]

        def park_nights(attribution: str, park: str) -> int:
            body = _statistics(
                client, _campus(client), park_org_id=park, group_by="none",
                attribution=attribution, **single,
            )
            return body["totals"]["nights"]

        # 快照口径按当晚楼栋：这一夜仍然算在西一区。
        snapshot_1, snapshot_3 = (park_nights("snapshot", p) for p in (west1, west3))
        # current 口径：只认当前在册楼栋，同一晚被算到 A5 所在的西三区。
        current_1, current_3 = (park_nights("current", p) for p in (west1, west3))
        assert (current_1, current_3) == (snapshot_1 - 1, snapshot_3 + 1)
    finally:
        with get_engine().begin() as conn:
            conn.execute(
                text("DELETE FROM residences WHERE residence_id = 'res_test_statistics_move'")
            )
            conn.execute(
                text("UPDATE residences SET valid_to = NULL WHERE student_id = :s AND building_id = 'bldg_a3'"),
                {"s": student},
            )


def test_trend_rows_cover_exactly_the_nights_with_facts(client) -> None:
    """趋势逐夜给出同一套三值，且与总计互相加得上。"""
    body = _statistics(client, _campus(client), group_by="trend")
    by_day = body["by_day"]
    assert body["rows"] == []
    assert [row["service_date"] for row in by_day] == sorted(row["service_date"] for row in by_day)
    assert sum(row["nights"] for row in by_day) == body["totals"]["nights"]
    assert sum(row["returns"] for row in by_day) == body["totals"]["returns"]
    assert len(by_day) <= HISTORY_NIGHTS
    # group_by 不是 trend 时同样给趋势，口径一致。
    plain = _statistics(client, _campus(client))
    assert plain["by_day"] == by_day


def test_empty_reservation_source_reports_real_zero(client) -> None:
    """预约源已接通：无预约时返回可验证的零，所有分组与总计一致。"""
    body = _statistics(client, _campus(client))
    assert body["totals"]["reservations"] == 0
    assert body["totals"]["unconfirmed"] == 0
    assert body["data_gaps"] == []
    assert all(row["reservations"] == 0 and row["unconfirmed"] == 0 for row in body["rows"])


def test_a_range_without_facts_still_reports_the_roster(client) -> None:
    """空区间：事实为 0，但在册分母照旧——园区要看的是「没有」而不是「查不到」。"""
    body = _statistics(client, _campus(client), date_from="2030-01-01", date_to="2030-01-07")
    zeros = {key: value for key, value in body["totals"].items() if key != "enrolled"}
    assert zeros == {
        "people": 0,
        "nights": 0,
        "returns": 0,
        "qr_returns": 0,
        "manual_returns": 0,
        "reservations": 0,
        "unconfirmed": 0,
    }
    assert body["totals"]["enrolled"] > 0
    assert body["rows"]
    assert all(r["returns"] == r["nights"] == r["people"] == 0 for r in body["rows"])
    assert sum(r["enrolled"] for r in body["rows"]) == body["totals"]["enrolled"]
    assert body["by_day"] == []


def test_default_range_is_the_last_fourteen_business_nights(client) -> None:
    """不给日期时默认近 14 夜；只给一端时就是那一夜。"""
    headers = _campus(client)
    default = client.get(f"{API}/statistics", headers=headers).json()["range"]
    assert (date.fromisoformat(default["date_to"]) - date.fromisoformat(default["date_from"])).days == 13
    single = client.get(f"{API}/statistics", headers=headers, params={"date_to": DATE_TO}).json()["range"]
    assert single == {"date_from": DATE_TO, "date_to": DATE_TO}


def test_statistics_rejects_bad_calibers(client) -> None:
    headers = _campus(client)
    for params in (
        {"group_by": "room"},
        {"attribution": "yesterday"},
        {"gender": "OTHER"},
        {"return_source": "FACE"},
        {"date_from": "2026-11-14", "date_to": "2026-11-01"},
        {"date_from": "1114"},
    ):
        response = client.get(f"{API}/statistics", headers=headers, params=params)
        assert response.status_code == 422, (params, response.text)
        assert response.json()["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("login_name", ["student", "dorm"])
def test_statistics_denies_roles_without_grant(client, login_name: str) -> None:
    """没有 statistics:read 的角色连选项都拿不到。

    辅导员、思政与学院负责人已改为「范围内可见」，其裁剪与越权另见范围用例。
    """
    headers = auth(token_for(client, login_name))
    for path in ("", "/filters"):
        response = client.get(f"{API}/statistics{path}", headers=headers, params=RANGE)
        assert response.status_code == 403, (login_name, path, response.text)
        assert response.json()["code"] == "FORBIDDEN_ACTION"
