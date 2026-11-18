"""宿管工号账号：园区统一注册分发，其他角色无入口（R19）。

并发与口令都走真实 PostgreSQL；用例之间靠 clean_db 清表。
"""

from fastapi.testclient import TestClient

from tests.conftest import API, auth, token_for

NEW_ACCOUNT = {"login_name": "dorm_a2", "display_name": "刘阿姨", "building_ids": ["bldg_a2"]}


def create(client: TestClient, campus_token: str, payload: dict | None = None) -> dict:
    response = client.post(
        f"{API}/staff-accounts", json=payload or NEW_ACCOUNT, headers=auth(campus_token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_campus_issues_account_and_staff_logs_in_with_initial_password(client, clean_db) -> None:
    campus = token_for(client, "campus")
    created = create(client, campus)

    assert created["account"]["status"] == "ACTIVE"
    assert created["account"]["building_ids"] == ["bldg_a2"]
    assert created["initial_password"]

    login = client.post(
        f"{API}/auth/mock-login",
        json={"login_name": "dorm_a2", "password": created["initial_password"]},
    )
    assert login.status_code == 200, login.text
    session = login.json()["session"]
    assert session["account_source"] == "STAFF_LOCAL"
    assert session["active_role"] == "DORM_MANAGER"
    # 雇佣人员没有校内邮箱：通知只落站内待办（R16、R19）。
    assert session["email"] is None
    assert session["scope"]["building_ids"] == ["bldg_a2"]


def test_wrong_password_for_staff_account_is_rejected(client, clean_db) -> None:
    campus = token_for(client, "campus")
    create(client, campus)
    response = client.post(
        f"{API}/auth/mock-login", json={"login_name": "dorm_a2", "password": "demo1234"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "BAD_CREDENTIALS"


def test_only_campus_reaches_account_endpoints(client, clean_db) -> None:
    for login_name in ("student", "counselor", "dorm"):
        token = token_for(client, login_name)
        listed = client.get(f"{API}/staff-accounts", headers=auth(token))
        assert listed.status_code == 403, login_name
        assert listed.json()["code"] == "FORBIDDEN_ACTION"
        created = client.post(f"{API}/staff-accounts", json=NEW_ACCOUNT, headers=auth(token))
        assert created.status_code == 403, login_name
        assert created.json()["details"]["action"].startswith("staff_account:")


def test_login_name_cannot_collide_with_seed_or_existing_account(client, clean_db) -> None:
    campus = token_for(client, "campus")
    duplicate_seed = client.post(
        f"{API}/staff-accounts",
        json={**NEW_ACCOUNT, "login_name": "dorm"},
        headers=auth(campus),
    )
    assert duplicate_seed.status_code == 409
    assert duplicate_seed.json()["code"] == "LOGIN_NAME_TAKEN"

    create(client, campus)
    duplicate_created = client.post(f"{API}/staff-accounts", json=NEW_ACCOUNT, headers=auth(campus))
    assert duplicate_created.status_code == 409
    assert duplicate_created.json()["code"] == "LOGIN_NAME_TAKEN"


def test_empty_building_list_is_rejected(client, clean_db) -> None:
    campus = token_for(client, "campus")
    response = client.post(
        f"{API}/staff-accounts",
        json={**NEW_ACCOUNT, "building_ids": []},
        headers=auth(campus),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_rebinding_buildings_applies_to_existing_session(client, clean_db) -> None:
    campus = token_for(client, "campus")
    created = create(client, campus)["account"]
    password = create_password(client, campus, created["id"])
    login = client.post(
        f"{API}/auth/mock-login", json={"login_name": "dorm_a2", "password": password}
    )
    assert login.status_code == 200, login.text
    staff_token = login.json()["token"]

    patched = client.patch(
        f"{API}/staff-accounts/{created['id']}",
        json={"building_ids": ["bldg_a2", "bldg_a3"]},
        headers=auth(campus),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["building_ids"] == ["bldg_a2", "bldg_a3"]

    current = client.get(f"{API}/me", headers=auth(staff_token)).json()
    assert current["scope"]["building_ids"] == ["bldg_a2", "bldg_a3"]


def create_password(client: TestClient, campus_token: str, account_id: str) -> str:
    """重置口令并返回新值：让「登录后再改绑」这类用例不必复用创建响应。"""
    response = client.post(
        f"{API}/staff-accounts/{account_id}/reset-password", headers=auth(campus_token)
    )
    assert response.status_code == 200, response.text
    return response.json()["initial_password"]


def test_reset_password_invalidates_old_session_and_old_password(client, clean_db) -> None:
    campus = token_for(client, "campus")
    created = create(client, campus)
    first = client.post(
        f"{API}/auth/mock-login",
        json={"login_name": "dorm_a2", "password": created["initial_password"]},
    ).json()

    second_password = create_password(client, campus, created["account"]["id"])

    assert client.get(f"{API}/me", headers=auth(first["token"])).status_code == 401
    old = client.post(
        f"{API}/auth/mock-login", json={"login_name": "dorm_a2", "password": created["initial_password"]}
    )
    assert old.status_code == 401
    fresh = client.post(
        f"{API}/auth/mock-login", json={"login_name": "dorm_a2", "password": second_password}
    )
    assert fresh.status_code == 200


def test_disable_kills_live_session_and_blocks_login(client, clean_db) -> None:
    campus = token_for(client, "campus")
    created = create(client, campus)
    staff_token = client.post(
        f"{API}/auth/mock-login",
        json={"login_name": "dorm_a2", "password": created["initial_password"]},
    ).json()["token"]

    disabled = client.post(
        f"{API}/staff-accounts/{created['account']['id']}/disable", headers=auth(campus)
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "DISABLED"
    assert disabled.json()["disabled_at"]

    # 同进程会话被立即清除；跨进程残留的会话由账号状态检查拦成 403 ACCOUNT_DISABLED。
    blocked = client.get(f"{API}/me", headers=auth(staff_token))
    assert blocked.status_code == 401
    assert blocked.json()["code"] == "SESSION_INVALID"

    again = client.post(
        f"{API}/auth/mock-login", json={"login_name": "dorm_a2", "password": created["initial_password"]}
    )
    assert again.status_code == 403
    assert again.json()["code"] == "ACCOUNT_DISABLED"


def test_staff_account_cannot_read_reservations_before_directory_lands(client, clean_db) -> None:
    """固定楼栋不等于数据范围已解析：目录落地前必须拒绝，不能返回空名单。"""
    campus = token_for(client, "campus")
    created = create(client, campus)
    token = client.post(
        f"{API}/auth/mock-login",
        json={"login_name": "dorm_a2", "password": created["initial_password"]},
    ).json()["token"]

    response = client.get(f"{API}/reservations", headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "SCOPE_UNRESOLVED"


def test_list_hides_passwords_and_keeps_list_shape(client, clean_db) -> None:
    campus = token_for(client, "campus")
    create(client, campus)
    body = client.get(f"{API}/staff-accounts", headers=auth(campus)).json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert all("password" not in item for item in body["items"])
