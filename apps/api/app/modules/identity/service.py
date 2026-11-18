"""模拟统一身份登录与多角色会话（Demo：明文合成口令，禁止写入真实凭据）。

登录名按来源分派（R18、R19）：校内统一账户走模拟统一身份，园区分发的宿管工号账号
查 `local_staff_accounts`。正式版必须由统一身份 + 目录关系自动识别身份并直接进入
对应工作台；Demo 阶段仍用登录页选择与 `/auth/role-switch` 轮换，见 docs/13。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.clock import Clock
from app.core.config import get_settings
from app.core.errors import ApiError
from app.modules.identity import staff_accounts
from app.modules.identity.adapters import mock_accounts
from app.modules.identity.schemas import Person, Role, SessionContext


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    token: str
    user_id: str
    active_role: Role
    expires_at: datetime
    rotated_from: str | None = None
    created_at: datetime | None = None


class SessionStore:
    """进程内会话表：切角色即轮换会话，旧令牌立即失效。

    生产实现换成学校 OIDC/CAS 会话 + 服务端存储；对外语义保持一致。
    """

    def __init__(self, clock: Clock, ttl: timedelta) -> None:
        self._clock = clock
        self._ttl = ttl
        self._by_token: dict[str, SessionRecord] = {}

    def login(self, login_name: str, password: str) -> SessionRecord:
        person = authenticate(login_name, password)
        return self._issue(person, self.default_role(person))

    def drop_user(self, user_id: str) -> None:
        """账号被停用或重置口令后，其已签发会话立即失效。"""
        for token, record in list(self._by_token.items()):
            if record.user_id == user_id:
                self._by_token.pop(token, None)

    def switch_role(self, session_id: str, role: Role) -> tuple[SessionRecord, Person]:
        record = self._find_by_session(session_id)
        person = self._person(record)
        if role not in person.roles:
            raise ApiError(
                403,
                "ROLE_NOT_ASSIGNED",
                "该账号未被授予此角色。",
                {"role": role.value, "assigned": [r.value for r in person.roles]},
            )
        new_record = self._issue(person, role, rotated_from=record.session_id)
        self._drop(record)
        return new_record, person

    def logout(self, session_id: str) -> None:
        record = self._find_by_session(session_id)
        self._drop(record)

    def resolve(self, token: str | None) -> tuple[SessionRecord, Person]:
        if not token:
            raise ApiError(401, "UNAUTHENTICATED", "缺少会话令牌。")
        record = self._by_token.get(token)
        if record is None or record.expires_at < self._clock.now():
            if record is not None:
                self._drop(record)
            raise ApiError(401, "SESSION_INVALID", "会话已失效，请重新登录。")
        return record, self._person(record)

    def context_of(self, record: SessionRecord) -> SessionContext:
        return self.context_for(record, self._person(record))

    def context_for(self, record: SessionRecord, person: Person) -> SessionContext:
        return SessionContext(
            session_id=record.session_id,
            user_id=person.user_id,
            school_id=person.school_id,
            display_name=person.display_name,
            roles=person.roles,
            active_role=record.active_role,
            scope=resolve_scope(person, record.active_role),
            expires_at=record.expires_at.isoformat(),
            account_source=person.account_source,
            email=person.email,
        )

    def default_role(self, person: Person) -> Role:
        """Demo：取授予列表里的第一个角色；正式版由目录关系判定，见模块 docstring。"""
        return person.roles[0]

    def _issue(
        self, person: Person, role: Role, rotated_from: str | None = None
    ) -> SessionRecord:
        self._purge_expired()
        record = SessionRecord(
            session_id=f"sess_{secrets.token_hex(8)}",
            token=secrets.token_urlsafe(32),
            user_id=person.user_id,
            active_role=role,
            expires_at=self._clock.now() + self._ttl,
            rotated_from=rotated_from,
        )
        self._by_token[record.token] = record
        return record

    def _find_by_session(self, session_id: str) -> SessionRecord:
        for record in self._by_token.values():
            if record.session_id == session_id:
                return record
        raise ApiError(401, "SESSION_INVALID", "会话不存在或已轮换。")

    def _person(self, record: SessionRecord) -> Person:
        person = mock_accounts.PEOPLE_BY_ID.get(record.user_id)
        if person is not None:
            return person
        staff = staff_accounts.find_person(record.user_id)
        if staff is None:
            raise ApiError(401, "SUBJECT_NOT_FOUND", "身份已不可用。")
        return staff

    def _drop(self, record: SessionRecord) -> None:
        self._by_token.pop(record.token, None)

    def _purge_expired(self) -> None:
        now = self._clock.now()
        for token, record in list(self._by_token.items()):
            if record.expires_at < now:
                del self._by_token[token]

    def clear(self) -> None:
        self._by_token.clear()


def authenticate(login_name: str, password: str) -> Person:
    """按登录名分派到两类账号来源（R18、R19）。

    种子账号（含演示用的 `dorm`）走统一 Demo 口令；园区运行时注册的工号账号
    用各自的口令。真实接入后统一账户改由学校身份系统校验，本函数只剩工号分支。
    """
    person = mock_accounts.PEOPLE_BY_LOGIN.get(login_name)
    if person is not None:
        if password != get_settings().demo_login_password:
            raise ApiError(401, "BAD_CREDENTIALS", "账号或口令不正确。")
        return person
    staff = staff_accounts.find_person_by_login(login_name, password)
    if staff is None:
        raise ApiError(401, "BAD_CREDENTIALS", "账号或口令不正确。")
    return staff


def person_by_user_id(user_id: str) -> Person | None:
    """按 user_id 取当前身份，供其他模块解析收件人；停用的工号账号视为不可用。"""
    person = mock_accounts.PEOPLE_BY_ID.get(user_id)
    if person is not None:
        return person
    try:
        return staff_accounts.find_person(user_id)
    except ApiError as exc:
        if exc.code == "ACCOUNT_DISABLED":
            return None
        raise


def resolve_scope(person: Person, role: Role) -> dict[str, object]:
    """数据范围解析。标注 pending 的项在 B 的目录模块落地后由适配器覆盖。"""
    if role is Role.STUDENT:
        return {"student_id": person.student_id, "resolved_by": "identity"}
    if role is Role.COUNSELOR:
        return {
            "counselor_user_id": person.user_id,
            "student_ids": [],
            "resolved_by": "pending:directory.get_counselors",
        }
    if role is Role.DORM_MANAGER:
        # 固定管理楼栋由园区授予（种子或工号表），有效值班范围仍需 B 的 duty 叠加，
        # 所以 resolved_by 保持 pending，避免目录未落地时返回空名单伪装成「没有预约」。
        return {
            "building_ids": list(person.home_building_ids),
            "resolved_by": "pending:duty_assignments",
        }
    return {"scope": "ALL_AUTHORIZED", "resolved_by": "campus_grant"}
