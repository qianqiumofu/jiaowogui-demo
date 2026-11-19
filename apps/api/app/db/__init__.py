"""数据库模型层：全仓库唯一的表定义入口。"""

from app.db.base import Base
from app.db.models import (
    BackgroundJob,
    Building,
    BuildingListSnapshot,
    CounselorAssignment,
    Device,
    DutyAssignment,
    ExportJob,
    Gate,
    Notification,
    Organization,
    PassCode,
    Residence,
    Reservation,
    ReservationRevision,
    ReturnRecord,
    Student,
    User,
)

__all__ = [
    "BackgroundJob",
    "Base",
    "Building",
    "BuildingListSnapshot",
    "CounselorAssignment",
    "Device",
    "DutyAssignment",
    "ExportJob",
    "Gate",
    "Notification",
    "Organization",
    "PassCode",
    "Residence",
    "Reservation",
    "ReservationRevision",
    "ReturnRecord",
    "Student",
    "User",
]
