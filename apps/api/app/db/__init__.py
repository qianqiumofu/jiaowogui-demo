"""B 主责的数据库模型层；A 的预约等表追加到同一个 Base。"""

from app.db.base import Base
from app.db.models import (
    Building,
    CounselorAssignment,
    Device,
    DutyAssignment,
    Gate,
    Organization,
    Residence,
    Student,
    User,
)

__all__ = [
    "Base",
    "Building",
    "CounselorAssignment",
    "Device",
    "DutyAssignment",
    "Gate",
    "Organization",
    "Residence",
    "Student",
    "User",
]
