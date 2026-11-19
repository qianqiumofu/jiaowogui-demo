from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import get_settings
from app.modules.identity.adapters import mock_accounts
from app.modules.identity.dependencies import ContextDep, get_session_store
from app.modules.identity.schemas import AccountSource, Role, SessionContext
from app.modules.identity.service import SessionStore

router = APIRouter(tags=["identity"])


class MockLoginRequest(BaseModel):
    login_name: str
    password: str


class RoleSwitchRequest(BaseModel):
    role: Role


class AuthSession(BaseModel):
    token: str
    session: SessionContext


class DemoAccount(BaseModel):
    user_id: str
    login_name: str
    display_name: str
    roles: list[Role]
    password: str
    account_source: AccountSource
    email: str | None = None


@router.get("/auth/demo-accounts", response_model=list[DemoAccount])
def demo_accounts() -> list[DemoAccount]:
    """演示种子账号；园区运行时注册的工号账号不在其中，需用表单输入账号与初始口令登录。"""
    password = get_settings().demo_login_password
    people=mock_accounts.PEOPLE
    if get_settings().database_url:
        from app.modules.identity.school import users,person
        people=[person(user_id=r["user_id"]) for r in users() if r["login_name"] in {"student","counselor","campus","dorm","ideology","teacher","college_admin","auth_admin","part_time_counselor"}]
    return [DemoAccount(user_id=p.user_id,login_name=p.login_name,display_name=p.display_name,roles=p.roles,password=password,account_source=p.account_source,email=p.email) for p in people if p]



@router.post("/auth/mock-login", response_model=AuthSession)
def mock_login(
    payload: MockLoginRequest, store: SessionStore = Depends(get_session_store)
) -> AuthSession:
    """统一账户与工号账号共用入口，来源判定见 `service.authenticate`。"""
    record = store.login(payload.login_name, payload.password)
    return AuthSession(token=record.token, session=store.context_of(record))


@router.get("/me", response_model=SessionContext)
def me(context: ContextDep) -> SessionContext:
    return context


@router.post("/auth/role-switch", response_model=AuthSession)
def role_switch(
    payload: RoleSwitchRequest,
    context: ContextDep,
    store: SessionStore = Depends(get_session_store),
) -> AuthSession:
    record, _ = store.switch_role(context.session_id, payload.role)
    return AuthSession(token=record.token, session=store.context_of(record))


@router.post("/auth/logout")
def logout(
    context: ContextDep, store: SessionStore = Depends(get_session_store)
) -> dict[str, str]:
    store.logout(context.session_id)
    return {"status": "logged_out"}


@router.get("/me/profile")
def profile(context:ContextDep):
    from app.modules.identity.service import person_by_user_id
    p=person_by_user_id(context.user_id)
    return {"user_id":p.user_id,"display_name":p.display_name,"identity_types":p.identity_types,"roles":[r.value for r in p.roles],"college_org_id":p.college_org_id,"student_id":p.student_id,"position_title":p.position_title}


@router.get("/me/residence")
def residence(context:ContextDep,store:SessionStore=Depends(get_session_store)):
    from app.core.errors import ApiError
    from app.modules.authorization.dependencies import authorize
    from app.modules.directory.service import get_residence
    authorize(context,"reservation:read")
    if context.active_role is not Role.STUDENT:raise ApiError(403,"FORBIDDEN_ACTION","只允许读取本人住宿。",{})
    return get_residence(context.scope["student_id"],store._clock.now()) or {}
