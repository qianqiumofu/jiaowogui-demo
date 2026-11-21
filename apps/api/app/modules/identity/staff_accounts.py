"""宿管工号账号服务（A 主责，身份底座范围）。

规则来源：R19——雇佣人员不进校内统一身份，账号、楼栋范围、口令重置与停用只由园区授予。
因此本模块的所有入口都挂在 `staff_account:*` 动作上，且仅 `CAMPUS` 角色可用。
工号账号与统一身份同存 `users` 表，靠 `source=STAFF_LOCAL` 区分；这类人员没有校内编号，
`school_id` 按登录名登记，与 `to_person` 给出的身份保持一致。
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import ApiError
from app.db.models import User
from app.modules.identity.adapters import mock_accounts
from app.modules.identity.schemas import AccountSource, Person, Role

PASSWORD_BYTES = 9
STAFF_LOCAL = AccountSource.STAFF_LOCAL.value


def new_staff_id(login_name: str) -> str:
    return f"usr_staff_{secrets.token_hex(10)}"


def generate_password() -> str:
    """初始口令：12 位左右的不透明串，只在创建/重置响应里返回一次。"""
    return secrets.token_urlsafe(PASSWORD_BYTES)


def to_person(account: User) -> Person:
    return Person(
        user_id=account.user_id,
        school_id=account.login_name,
        display_name=account.display_name,
        login_name=account.login_name,
        roles=[Role.DORM_MANAGER],
        account_source=AccountSource.STAFF_LOCAL,
        email=None,
        home_building_ids=list(account.building_ids),
        identity_types=["EMPLOYEE"],position_title="宿管",
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
    from app.modules.directory.service import assert_buildings_exist
    assert_buildings_exist(cleaned)
    return cleaned


def _local_only():
    return select(User).where(User.source == STAFF_LOCAL)


def get_account(session: Session, account_id: str) -> User:
    account = session.scalar(_local_only().where(User.user_id == account_id))
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
) -> tuple[User, str]:
    login = login_name.strip()
    if login in mock_accounts.PEOPLE_BY_LOGIN:
        raise _login_name_taken(login)
    account = User(
        user_id=new_staff_id(login),
        school_id=login,
        login_name=login,
        display_name=display_name.strip(),
        source=STAFF_LOCAL,
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


def list_accounts(session: Session) -> list[User]:
    return list(session.scalars(_local_only().order_by(User.login_name)))


def update_account(
    session: Session,
    account_id: str,
    *,
    display_name: str | None,
    building_ids: list[str] | None,
) -> User:
    account = get_account(session, account_id)
    if display_name is not None:
        account.display_name = display_name.strip()
    if building_ids is not None:
        account.building_ids = _clean_building_ids(building_ids)
    session.commit()
    return account


def unbind_building(session: Session, account_id: str, building_id: str) -> None:
    """参加调用方事务的楼栋解绑；行锁避免覆盖园区并发修改，不自行提交。"""
    account = session.scalar(
        _local_only().where(User.user_id == account_id).with_for_update()
    )
    if account is not None and building_id in account.building_ids:
        account.building_ids = [value for value in account.building_ids if value != building_id]
        session.flush()


def reset_password(session: Session, account_id: str) -> tuple[User, str]:
    account = get_account(session, account_id)
    account.password = generate_password()
    session.commit()
    return account, account.password


def remove_building_binding(session: Session, account_id: str, building_id: str) -> None:
    """参与调用方事务的楼栋解绑；与名册撤权原子完成，不自行提交。"""
    account = session.scalar(
        _local_only().where(User.user_id == account_id).with_for_update()
    )
    if account is not None:
        account.building_ids = [b for b in account.building_ids if b != building_id]


def disable(session: Session, clock: Clock, account_id: str) -> User:
    """停用只作用于工号账号；统一账户的冻结归校方身份系统，本系统无入口。"""
    account = get_account(session, account_id)
    account.status = "DISABLED"
    account.disabled_at = clock.now()
    session.commit()
    return account


def enable(session: Session, account_id: str) -> User:
    """恢复已停用的工号账号为在用，清除停用时间；楼栋范围沿用账号当前绑定。"""
    account = get_account(session, account_id)
    account.status = "ACTIVE"
    account.disabled_at = None
    session.commit()
    return account


def _open_session() -> SqlSession:
    """统一登录入口在没有命中种子账号时才连库，数据库未启动按 503 处理。"""
    from sqlalchemy.orm import Session as SqlSession

    from app.core.db import get_engine

    return SqlSession(get_engine())


def _assert_active(account: User) -> None:
    if account.status == "ACTIVE":
        return
    raise ApiError(
        403,
        "ACCOUNT_DISABLED",
        "该工号账号已由园区停用，请联系园区管理员。",
        {
            "staff_account_id": account.user_id,
            "disabled_at": account.disabled_at.isoformat() if account.disabled_at else None,
        },
    )


def find_person_by_login(login_name: str, password: str) -> Person | None:
    """登录分派的第二跳：种子账号未命中时查库里的工号账号。"""
    with _open_session() as session:
        account = session.scalar(_local_only().where(User.login_name == login_name))
        if account is None:
            return None
        if password != account.password:
            raise ApiError(401, "BAD_CREDENTIALS", "账号或口令不正确。")
        _assert_active(account)
        return to_person(account)


def find_person(user_id: str) -> Person | None:
    """按 user_id 取工号账号的当前身份，让改绑楼栋与停用立刻作用于已有会话。"""
    with _open_session() as session:
        account = session.scalar(_local_only().where(User.user_id == user_id))
        if account is None:
            return None
        _assert_active(account)
        return to_person(account)


def fixed_buildings(user_id):
    with _open_session() as db:
        user=db.scalar(_local_only().where(User.user_id==user_id,User.status=="ACTIVE"))
        return list(user.building_ids) if user else []


def fixed_staff(building_id):
    with _open_session() as db:
        return [r.user_id for r in db.scalars(_local_only().where(User.status=="ACTIVE")) if building_id in r.building_ids]


def active_staff(user_ids):
    if not user_ids:return []
    with _open_session() as db:
        return list(db.scalars(select(User.user_id).where(User.user_id.in_(user_ids),User.status=="ACTIVE",User.source==STAFF_LOCAL)))


def demo_login_account_ids(password: str) -> set[str]:
    """仅供演示快捷登录筛选；已重置口令的工号账号必须手工登录，不返回其口令。"""
    with _open_session() as db:
        return set(db.scalars(select(User.user_id).where(
            User.source == STAFF_LOCAL, User.status == "ACTIVE", User.password == password
        )))
