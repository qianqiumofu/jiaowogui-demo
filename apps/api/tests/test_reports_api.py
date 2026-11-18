"""报告接口的权限与入口行为（M4 A 侧第二块）。

`/reports/daily`、`/reports/weekly` 是只读入口，但「读哪些学生」完全由负责关系决定，
所以范围没同步时必须挡住，不能退化成全校可读。策略与范围判定不需要数据库；
带令牌的端到端用例依赖真实 PostgreSQL，未就绪时明确 skip。
"""

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ApiError
from app.modules.authorization.dependencies import authorize
from app.modules.authorization.policies import is_allowed
from app.modules.identity.schemas import AccountSource, Role, SessionContext
from app.modules.reports import readmodel
from tests.conftest import API, auth, token_for

PENDING_SCOPE = {"student_ids": [], "resolved_by": "pending:directory.get_counselors"}
SYNCED_SCOPE = {"student_ids": ["stu_synth_0001"], "resolved_by": "directory"}


def context(role: Role, scope: dict[str, object]) -> SessionContext:
    return SessionContext(
        session_id="ses_test",
        user_id="usr_synth_0002",
        school_id="T2001",
        display_name="李辅导员",
        roles=[role],
        active_role=role,
        scope=scope,
        expires_at="2026-11-17T08:00:00+08:00",
        account_source=AccountSource.UNIFIED_SCHOOL,
    )


def test_only_counselors_are_granted_report_read() -> None:
    for role in (Role.STUDENT, Role.DORM_MANAGER, Role.CAMPUS):
        assert is_allowed(role, "report:read") is False
    assert is_allowed(Role.COUNSELOR, "report:read") is True


def test_pending_directory_blocks_the_read() -> None:
    with pytest.raises(ApiError) as caught:
        authorize(context(Role.COUNSELOR, PENDING_SCOPE), "report:read")
    assert caught.value.status_code == 403
    assert caught.value.code == "SCOPE_UNRESOLVED"


def test_resolved_directory_narrows_the_read_to_assigned_students() -> None:
    assert readmodel.student_ids_of(context(Role.COUNSELOR, SYNCED_SCOPE)) == ["stu_synth_0001"]
    assert readmodel.student_ids_of(context(Role.COUNSELOR, PENDING_SCOPE)) == []


def test_empty_assignment_is_not_the_same_as_full_access() -> None:
    """空列表＝一个都不给看；只有显式 `None` 才是不按学生收窄。"""
    assert readmodel.scope_for([]) == {"student_ids": [], "resolved_by": "identity"}
    assert readmodel.scope_for(None)["scope"] == "ALL_AUTHORIZED"


def test_without_token_is_401(client: TestClient) -> None:
    for path in ("/reports/daily", "/reports/weekly"):
        response = client.get(f"{API}{path}")
        assert response.status_code == 401, response.text
        assert response.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.usefixtures("clean_db")
def test_counselor_read_is_blocked_until_the_directory_lands(client: TestClient) -> None:
    """端到端确认现在报的是 403 而不是空数据：空数据会被前端当成「当晚没人」。"""
    token = token_for(client, "counselor")
    for path in ("/reports/daily", "/reports/weekly"):
        response = client.get(f"{API}{path}", headers=auth(token))
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "SCOPE_UNRESOLVED"


@pytest.mark.usefixtures("clean_db")
def test_other_roles_cannot_read_reports(client: TestClient) -> None:
    for login_name in ("student", "dorm", "campus"):
        response = client.get(f"{API}/reports/daily", headers=auth(token_for(client, login_name)))
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN_ACTION"
