"""宿管工号账号服务（A 主责，身份底座范围）。

规则来源：R19——雇佣人员不进校内统一身份，账号、楼栋范围、口令重置与停用只由园区授予。
因此本模块的所有入口都挂在 `staff_account:*` 动作上，且仅 `CAMPUS` 角色可用。
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import ApiError
from app.db.models import LocalStaffAccount
from app.modules.identity.adapters import mock_accounts
from app.modules.identity.schemas import AccountSource, Person, Role

PASSWORD_BYTES = 9


def new_staff_id(login_name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in login_name)[:24]
    return f"usr_staff_{slug}"


def generate_password() -> str:
    """初始口令：12 位左右的不透明串，只在创建/重置响应里返回一次。"""
    return secrets.token_urlsafe(PASSWORD_BYTES)


def to_person(account: LocalStaffAccount) -> Person:
    return Person(
        user_id=account.id,
        school_id=account.login_name,
        display_name=account.display_name,
        login_name=account.login_name,
        roles=[Role.DORM_MANAGER],
        account_source=AccountSource.STAFF_LOCAL,
        email=None,
        home_building_ids=list(account.building_ids),
    )


def _clean_building_ids(building_ids: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in building_ids:
        value = raw.strip()
        if not value:
            raise ApiError(
                422,
                "VALIDATION_FAILED",
                "楼栋编号不能为空。",
                {"field": "building_ids"},
            )
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def get_account(session: Session, account_id: str) -> LocalStaffAccount:
    account = session.get(LocalStaffAccount, account_id)
    if account is None:
        raise ApiError(
            404,
            "STAFF_ACCOUNT_NOT_FOUND",
            "工号账号不存在。",
            {"staff_account_id": account_id},
        )
    return account


def create_account(
    session: Session, *, login_name: str, display_name: str, building_ids: list[str]
) -> tuple[LocalStaffAccount, str]:
    login = login_name.strip()
    if login in mock_accounts.PEOPLE_BY_LOGIN:
        raise _login_name_taken(login)
    account = LocalStaffAccount(
        id=new_staff_id(login),
        login_name=login,
        display_name=display_name.strip(),
        password=generate_password(),
        building_ids=_clean_building_ids(building_ids),
        status="ACTIVE",
    )
    try:
        session.add(account)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise _login_name_taken(login) from None
    return account, account.password


def _login_name_taken(login: str) -> ApiError:
    return ApiError(
        409,
        "LOGIN_NAME_TAKEN",
        "登录名已被占用，不能与统一账户或其他工号账号重复。",
        {"login_name": login},
    )


def list_accounts(session: Session) -> list[LocalStaffAccount]:
    return list(session.scalars(select(LocalStaffAccount).order_by(LocalStaffAccount.login_name)))


def update_account(
    session: Session,
    account_id: str,
    *,
    display_name: str | None,
    building_ids: list[str] | None,
) -> LocalStaffAccount:
    account = get_account(session, account_id)
    if display_name is not None:
        account.display_name = display_name.strip()
    if building_ids is not None:
        account.building_ids = _clean_building_ids(building_ids)
    session.commit()
    return account


def reset_password(session: Session, account_id: str) -> tuple[LocalStaffAccount, str]:
    account = get_account(session, account_id)
    account.password = generate_password()
    session.commit()
    return account, account.password


def disable(session: Session, clock: Clock, account_id: str) -> LocalStaffAccount:
    """停用只作用于工号账号；统一账户的冻结归校方身份系统，本系统无入口。"""
    account = get_account(session, account_id)
    account.status = "DISABLED"
    account.disabled_at = clock.now()
    session.commit()
    return account


def _open_session() -> SqlSession:
    """统一登录入口在没有命中种子账号时才连库，数据库未启动按 503 处理。"""
    from sqlalchemy.orm import Session as SqlSession

    from app.core.db import get_engine

    return SqlSession(get_engine())


def _assert_active(account: LocalStaffAccount) -> None:
    if account.status == "ACTIVE":
        return
    raise ApiError(
        403,
        "ACCOUNT_DISABLED",
        "该工号账号已由园区停用，请联系园区管理员。",
        {
            "staff_account_id": account.id,
            "disabled_at": account.disabled_at.isoformat() if account.disabled_at else None,
        },
    )


def find_person_by_login(login_name: str, password: str) -> Person | None:
    """登录分派的第二跳：种子账号未命中时查本地工号表。"""
    with _open_session() as session:
        account = session.scalar(
            select(LocalStaffAccount).where(LocalStaffAccount.login_name == login_name)
        )
        if account is None:
            return None
        if password != account.password:
            raise ApiError(401, "BAD_CREDENTIALS", "账号或口令不正确。")
        _assert_active(account)
        return to_person(account)


def find_person(user_id: str) -> Person | None:
    """按 user_id 取工号账号的当前身份，让改绑楼栋与停用立刻作用于已有会话。"""
    with _open_session() as session:
        account = session.get(LocalStaffAccount, user_id)
        if account is None:
            return None
        _assert_active(account)
        return to_person(account)
