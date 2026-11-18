"""现场补录选人：本楼栋名册按姓名/学号检索，值班级范围与字段级（不含联系方式）校验。

对应基线 R11（宿管可手动记录按门铃等实际返宿情况，权限按有效值班范围校验）。
补录用 `building_residents:read_duty`，与 `/return-records/manual` 共用同一份值班范围。
"""

from tests.conftest import API, auth, jump_clock, token_for


def test_residents_search_locks_identity_by_school_id_within_duty(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)

    response = client.get(
        f"{API}/directory/buildings/bldg_a1/residents",
        headers=auth(token),
        params={"q": "2023S0001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["building_id"] == "bldg_a1"
    assert body["next_cursor"] is None
    hit = {item["student_id"]: item for item in body["items"]}
    assert "stu_synth_0001" in hit
    locked = hit["stu_synth_0001"]
    assert locked["school_id"] == "2023S0001"
    assert locked["building_id"] == "bldg_a1"
    assert locked["room_no"] == "A1-301"
    assert locked["display_name"]
    # 性别是园区端统计维度之一（R14），名册直接可读。
    assert locked["gender"] == "MALE"
    # 字段级权限：名册只给身份，联系方式必须另走 contact:read_duty。
    assert "phone" not in locked
    assert "college_org_id" not in locked


def test_empty_query_lists_the_whole_building_roster_sorted_by_school_id(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)

    body = client.get(
        f"{API}/directory/buildings/bldg_a1/residents", headers=auth(token)
    ).json()
    school_ids = [item["school_id"] for item in body["items"]]
    assert school_ids  # 本楼栋有名册
    assert school_ids == sorted(school_ids)
    assert all(item["building_id"] == "bldg_a1" for item in body["items"])


def test_residents_search_denies_buildings_outside_the_duty(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)

    outside = client.get(
        f"{API}/directory/buildings/bldg_a2/residents", headers=auth(token)
    )
    assert outside.status_code == 403
    assert outside.json()["code"] == "OUT_OF_SCOPE"
    assert outside.json()["details"]["allowed"] == ["bldg_a1"]


def test_residents_search_is_dorm_manager_only(client) -> None:
    jump_clock(client, 20)
    for login_name in ("student", "counselor", "campus"):
        token = token_for(client, login_name)
        refused = client.get(
            f"{API}/directory/buildings/bldg_a1/residents", headers=auth(token)
        )
        assert refused.status_code == 403, (login_name, refused.text)
        assert refused.json()["code"] == "FORBIDDEN_ACTION"
