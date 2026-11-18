"""目录、住宿、负责与代班关系、后台任务表（B 主责）。

ID 为不透明字符串，演示数据固定 ID 见 docs/10-演示数据与账号.md；
时间一律带时区，业务日判定只用 app.core.clock，不由客户端决定。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ORG_TYPES = ("COLLEGE", "CAMPUS_PARK")
_STUDENT_GENDERS = ("MALE", "FEMALE")
_JOB_STATUS = ("PENDING", "RUNNING", "DONE", "FAILED")
_PASS_STATUS = ("ISSUED", "CONSUMED", "EXPIRED", "REVOKED")
_RETURN_SOURCE = ("QR", "MANUAL")
_EXPORT_REPORTS = ("STATISTICS",)
_EXPORT_STATUS = ("PENDING", "RUNNING", "DONE", "FAILED")


def _device_token_digest(context) -> str:
    """合成设备令牌摘要：真机联调时换成设备侧下发的密钥，库里始终只存摘要。"""
    device_id = context.get_current_parameters()["device_id"]
    return hashlib.sha256(f"dev_synth:{device_id}".encode()).hexdigest()


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(f"org_type IN {_ORG_TYPES}", name="ck_organizations_type"),
    )

    org_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    org_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.org_id")
    )


class Building(Base):
    __tablename__ = "buildings"

    building_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    campus_org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.org_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class Gate(Base):
    __tablename__ = "gates"

    gate_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    gate_id: Mapped[str] = mapped_column(ForeignKey("gates.gate_id"), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    token_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, default=_device_token_digest
    )


class User(Base):
    """目录侧的人员登记；角色与登录仍由 A 的 identity 模块判定。"""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    login_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        # 性别是统计维度之一（R14），合成值；实际字段以学校目录映射为准（R02）。
        CheckConstraint(f"gender IN {_STUDENT_GENDERS}", name="ck_students_gender"),
    )

    student_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    college_org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.org_id"), nullable=False
    )
    grade: Mapped[str] = mapped_column(String(8), nullable=False)
    gender: Mapped[str] = mapped_column(String(8), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)


class Residence(Base):
    __tablename__ = "residences"
    __table_args__ = (
        UniqueConstraint("student_id", "valid_from", name="uq_residence_per_night_start"),
    )

    residence_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id"), nullable=False)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id"), nullable=False
    )
    room_no: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)


class CounselorAssignment(Base):
    __tablename__ = "counselor_assignments"
    __table_args__ = (
        UniqueConstraint(
            "counselor_user_id", "student_id", "valid_from", name="uq_counselor_assignment"
        ),
    )

    assignment_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    counselor_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)


class DutyAssignment(Base):
    """值班与代班：权限只在 shift_start..shift_end 的生效区间内成立（R11）。"""

    __tablename__ = "duty_assignments"
    __table_args__ = (
        UniqueConstraint(
            "staff_user_id", "building_id", "service_date", "shift_start", name="uq_duty_slot"
        ),
    )

    duty_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    staff_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id"), nullable=False
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_substitute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BackgroundJob(Base):
    """唯一调度表，语义与 app/worker/registry.py 的 SQL 对齐。"""

    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {_JOB_STATUS}", name="ck_background_jobs_status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    business_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BuildingListSnapshot(Base):
    """24:00 汇总快照：住宿与学院按发生时取值，之后的改期与返宿不回写快照（R12）。"""

    __tablename__ = "building_list_snapshots"
    __table_args__ = (
        UniqueConstraint("building_id", "service_date", name="uq_snapshot_night"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id"), nullable=False
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PassCode(Base):
    """夜行通行码：核验结果与预约版本、楼栋、门点绑定，一次使用（R08、R09）。

    `reservation_id` 只按 ID 引用 A 的预约，不加外键：预约表由 A 落地，
    B 的迁移不依赖对方建表顺序。同一预约最多一个 ISSUED 码，唯一性由迁移的部分索引保证。
    """

    __tablename__ = "pass_codes"
    __table_args__ = (
        CheckConstraint(f"status IN {_PASS_STATUS}", name="ck_pass_codes_status"),
    )

    pass_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id"), nullable=False)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id"), nullable=False
    )
    gate_id: Mapped[str | None] = mapped_column(ForeignKey("gates.gate_id"))
    verification_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reservation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ISSUED")


class ReturnRecord(Base):
    """正式返宿事实，唯一写入方是 returns 模块；一学生一业务夜最多一条（R10）。

    `occurred_at` 是返宿发生时间，`recorded_at` 是记录时间；人工补录不改发生时间。
    """

    __tablename__ = "return_records"
    __table_args__ = (
        UniqueConstraint("student_id", "service_date", name="uq_return_per_night"),
        CheckConstraint(f"source IN {_RETURN_SOURCE}", name="ck_return_records_source"),
    )

    return_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    pass_id: Mapped[str | None] = mapped_column(ForeignKey("pass_codes.pass_id"))
    gate_id: Mapped[str | None] = mapped_column(ForeignKey("gates.gate_id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)


class ExportJob(Base):
    """园区受控导出任务（B 主责，`export:create` 字段级权限）。

    只登记统计口径与聚合结果，不落明细行，所以联系方式随口径一起被排除在导出范围外（R11）。
    `csv_content` 存渲染好的 UTF-8 CSV（带 BOM，Excel 双击不乱码）。
    超过保留期后读取路径会清空内容、保留这一行做审计（谁在什么时候导了哪个区间），
    下载改判 410；取值见配置 `EXPORT_RETENTION_DAYS`。
    """

    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(f"report IN {_EXPORT_REPORTS}", name="ck_export_jobs_report"),
        CheckConstraint(f"status IN {_EXPORT_STATUS}", name="ck_export_jobs_status"),
    )

    export_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    report: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    file_name: Mapped[str | None] = mapped_column(String(128))
    csv_content: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
