from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    STUDENT = "STUDENT"
    DORM_MANAGER = "DORM_MANAGER"
    COUNSELOR = "COUNSELOR"
    CAMPUS = "CAMPUS"


class AccountSource(str, Enum):
    """账号来源；决定口令由谁校验、通知走哪个渠道（R18、R19）。"""

    UNIFIED_SCHOOL = "UNIFIED_SCHOOL"
    STAFF_LOCAL = "STAFF_LOCAL"


class Person(BaseModel):
    """合成身份；真实接入后由 IdentityProvider + DirectoryProvider 提供。"""

    user_id: str
    school_id: str
    display_name: str
    login_name: str
    roles: list[Role]
    account_source: AccountSource = AccountSource.UNIFIED_SCHOOL
    email: str | None = None
    student_id: str | None = None
    home_building_ids: list[str] = Field(default_factory=list)


class StaffAccountCreate(BaseModel):
    login_name: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    building_ids: list[str] = Field(min_length=1)


class StaffAccountPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    building_ids: list[str] | None = Field(default=None, min_length=1)


class SessionContext(BaseModel):
    session_id: str
    user_id: str
    school_id: str
    display_name: str
    roles: list[Role]
    active_role: Role
    scope: dict[str, object]
    expires_at: str
    account_source: AccountSource
    email: str | None = None
