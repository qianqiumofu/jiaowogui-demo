import pytest
"""四角色越权检查：权限由后端执行，前端隐藏只是辅助。"""

from tests.conftest import API, auth, jump_clock, token_for


pytestmark = pytest.mark.usefixtures("seeded_demo_db")

def test_student_reads_own_scope_and_is_denied_building_list(client) -> None:
    token = token_for(client, "student")
    context = client.get(f"{API}/me", headers=auth(token)).json()
    assert context["active_role"] == "STUDENT"
    assert context["scope"]["student_id"] == "stu_synth_0001"

    # 预约列表已接入真实数据库，其行为在 tests/test_reservation_flow.py（需 PostgreSQL）覆盖。
    denied = client.get(f"{API}/buildings/bldg_a1/tonight", headers=auth(token))
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN_ACTION"


def test_seed_accounts_expose_account_source(client) -> None:
    """统一账户带合成校内邮箱，宿管种子账号属园区分发的工号账号（R18、R19）。"""
    student = client.get(f"{API}/me", headers=auth(token_for(client, "student"))).json()
    assert student["account_source"] == "UNIFIED_SCHOOL"
    assert student["email"] == "2023S0001@synth.edu.cn"

    jump_clock(client, 20)
    dorm = client.get(f"{API}/me", headers=auth(token_for(client, "dorm"))).json()
    assert dorm["account_source"] == "STAFF_LOCAL"
    assert dorm["email"] is None
    assert dorm["scope"]["building_ids"] == ["bldg_a1"]


def test_without_token_is_401(client) -> None:
    response = client.get(f"{API}/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_bad_password_rejected(client) -> None:
    response = client.post(f"{API}/auth/mock-login", json={"login_name": "student", "password": "x"})
    assert response.status_code == 401
    assert response.json()["code"] == "BAD_CREDENTIALS"


def test_role_switch_rotates_session(client) -> None:
    login = client.post(
        f"{API}/auth/mock-login", json={"login_name": "counselor", "password": "demo1234"}
    ).json()
    old_token = login["token"]
    switched = client.post(
        f"{API}/auth/role-switch", json={"role": "STUDENT"}, headers=auth(old_token)
    )
    assert switched.status_code == 200, switched.text
    new = switched.json()
    assert new["session"]["active_role"] == "STUDENT"
    assert new["token"] != old_token
    assert new["session"]["session_id"] != login["session"]["session_id"]
    assert client.get(f"{API}/me", headers=auth(old_token)).status_code == 401
    assert client.get(f"{API}/me", headers=auth(new["token"])).status_code == 200


def test_unassigned_role_switch_is_rejected(client) -> None:
    token = token_for(client, "student")
    response = client.post(f"{API}/auth/role-switch", json={"role": "CAMPUS"}, headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "ROLE_NOT_ASSIGNED"


def test_counselor_scope_comes_from_directory(client) -> None:
    token = token_for(client, "counselor")
    context = client.get(f"{API}/me", headers=auth(token)).json()
    assert context["scope"]["resolved_by"] == "directory"
    assert context["scope"]["student_ids"] == [
        f"stu_synth_{n:04d}" for n in range(1, 7)
    ]
    assert client.get(f"{API}/risk-events", headers=auth(token)).status_code == 200


def test_dorm_manager_scope_follows_the_effective_duty_window(client) -> None:
    token = token_for(client, "dorm")
    before_substitute = jump_clock(client, 22, 59)
    scope = client.get(f"{API}/me", headers=auth(token)).json()["scope"]
    assert scope["resolved_by"] == "duty_assignments"
    assert scope["building_ids"] == ["bldg_a1"], before_substitute

    during_substitute = jump_clock(client, 23, 1)
    scope = client.get(f"{API}/me", headers=auth(token)).json()["scope"]
    assert sorted(scope["building_ids"]) == ["bldg_a1", "bldg_a2"], during_substitute


def test_dorm_manager_reads_current_building_list(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)
    response = client.get(f"{API}/buildings/bldg_a1/tonight", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["building_id"] == "bldg_a1"
    assert response.json()["items"] == []


def test_dorm_manager_cannot_read_unrostered_building(client) -> None:
    token = token_for(client, "dorm")
    jump_clock(client, 20)
    response = client.get(f"{API}/buildings/bldg_a2/tonight", headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "OUT_OF_SCOPE"


def test_campus_queries_risk_but_cannot_ack(client) -> None:
    token = token_for(client, "campus")
    listed = client.get(f"{API}/risk-events", headers=auth(token))
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    ack = client.post(f"{API}/risk-events/risk_1/ack", headers=auth(token))
    assert ack.status_code == 403
    assert ack.json()["code"] == "FORBIDDEN_ACTION"


def test_authz_actions_reflect_role(client) -> None:
    token = token_for(client, "student")
    body = client.get(f"{API}/authz/actions", headers=auth(token)).json()
    assert "reservation:create" in body["allowed_actions"]
    assert "manual_return:create" not in body["allowed_actions"]


def test_counselor_cannot_switch_duty(client) -> None:
    token = token_for(client, "counselor")
    response = client.post(f"{API}/duty-assignments/switch", json={}, headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"


def test_dorm_manager_cannot_self_assign_duty(client) -> None:
    token = token_for(client, "dorm")
    # 值班范围只在班次窗口内成立：不推进演示时钟，本用例会在白天空转成 SCOPE_UNRESOLVED。
    jump_clock(client, 19, 0)
    response = client.post(f"{API}/duty-assignments/switch", json={}, headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"


def test_campus_cannot_list_reservations(client) -> None:
    token = token_for(client, "campus")
    response = client.get(f"{API}/reservations", headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"
