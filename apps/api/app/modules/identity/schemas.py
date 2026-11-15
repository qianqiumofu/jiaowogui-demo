from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    STUDENT = "STUDENT"
    DORM_MANAGER = "DORM_MANAGER"
    COUNSELOR = "COUNSELOR"
    CAMPUS = "CAMPUS"


class Person(BaseModel):
    """合成身份；真实接入后由 IdentityProvider + DirectoryProvider 提供。"""

    user_id: str
    school_id: str
    display_name: str
    login_name: str
    roles: list[Role]
    student_id: str | None = None
    home_building_ids: list[str] = Field(default_factory=list)


class SessionContext(BaseModel):
    session_id: str
    user_id: str
    school_id: str
    display_name: str
    roles: list[Role]
    active_role: Role
    scope: dict[str, object]
    expires_at: str
