from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.modules.identity.adapters import mock_accounts
from app.modules.identity.dependencies import ContextDep, get_session_store
from app.modules.identity.schemas import Role, SessionContext
from app.modules.identity.service import DEMO_PASSWORD, SessionStore

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
    login_name: str
    display_name: str
    roles: list[Role]
    password: str


@router.get("/auth/demo-accounts", response_model=list[DemoAccount])
def demo_accounts() -> list[DemoAccount]:
    return [
        DemoAccount(
            login_name=p.login_name,
            display_name=p.display_name,
            roles=p.roles,
            password=DEMO_PASSWORD,
        )
        for p in mock_accounts.PEOPLE
    ]


@router.post("/auth/mock-login", response_model=AuthSession)
def mock_login(
    payload: MockLoginRequest, store: SessionStore = Depends(get_session_store)
) -> AuthSession:
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
