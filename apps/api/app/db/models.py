"""全仓库唯一的表定义：目录、住宿、负责与代班、签码与返宿、导出，以及预约与通知。

一套数据库、一个 Base：A 的预约/修订/通知表和 B 的目录/任务表都注册在同一份 metadata 上，
迁移按 0001—0009（B 的目录底座）→ 0010—0012（A 的预约与通知）→ 0013（工号账号并入 users）串成单头。
ID 为不透明字符串，演示数据固定 ID 见 docs/10-演示数据与账号.md；
时间一律带时区，业务日判定只用 app.core.clock，不由客户端决定。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Time,
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
_ACCOUNT_SOURCES = ("UNIFIED_SCHOOL", "STAFF_LOCAL")
_ACCOUNT_STATUS = ("ACTIVE", "DISABLED")
_RESERVATION_STATUS = ("ACTIVE", "CANCELLED", "FULFILLED", "CLOSED")
_REVISION_SOURCES = ("CREATE", "RESCHEDULE", "CANCEL", "RESTORE", "CLOSE")
_NOTIFICATION_TEMPLATES = ("NIGHT_ROSTER", "DAILY_REPORT", "WEEKLY_REPORT", "RISK_ALERT", "DORM_APPROVED", "DORM_RESCHEDULED", "DORM_CANCELLED")
_NOTIFICATION_CHANNELS = ("EMAIL", "INBOX")
_NOTIFICATION_STATUS = ("SENT", "READ")

NOTIFICATION_JOB_TYPE = "NOTIFICATION_SEND"


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
    """全仓库唯一的人员表：统一身份账户与园区注册的工号账号同表（R18、R19）。

    `source` 决定投递渠道与口令校验方：`UNIFIED_SCHOOL` 带校内邮箱、口令由校方校验；
    `STAFF_LOCAL` 没有邮箱，同一事件只落站内待办，口令是 Demo 明文合成值，禁止写真实凭据。
    角色与登录仍由 A 的 identity 模块判定。
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"source IN {_ACCOUNT_SOURCES}", name="ck_users_source"),
        CheckConstraint(f"status IN {_ACCOUNT_STATUS}", name="ck_users_status"),
    )

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    login_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="UNIFIED_SCHOOL")
    password: Mapped[str | None] = mapped_column(String(64))
    building_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    identity_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    college_org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.org_id"))
    position_title: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        # 性别是统计维度之一（R14），合成值；实际字段以学校目录映射为准（R02）。
        CheckConstraint(f"gender IN {_STUDENT_GENDERS}", name="ck_students_gender"),
        CheckConstraint("education_level IN ('BACHELOR', 'MASTER', 'DOCTORAL')", name="ck_students_education_level"),
    )

    student_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"))
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    college_org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.org_id"), nullable=False
    )
    major: Mapped[str] = mapped_column(String(64), nullable=False, default="合成专业", server_default="合成专业")
    class_name: Mapped[str] = mapped_column(String(32), nullable=False, default="合成班级", server_default="合成班级")
    education_level: Mapped[str | None] = mapped_column(String(16))
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


class BuildingDutyRoster(Base):
    """楼栋固定值班名册：园区端维护的长期值守范围，`duty_assignments` 只留按夜代班。

    `shift_start/shift_end` 是每晚重复的时刻段而非时间戳，跨零点由读取侧回绕判定，
    所以同一栋楼可以并排白班与夜班两位；`valid_from/valid_to` 只框定覆盖的业务夜区间。
    """

    __tablename__ = "building_duty_roster"
    __table_args__ = (
        UniqueConstraint("building_id", "staff_user_id", name="uq_duty_roster_slot"),
        CheckConstraint("shift_start <> shift_end", name="ck_duty_roster_window"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="ck_duty_roster_valid_range"
        ),
    )

    roster_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    building_id: Mapped[str] = mapped_column(
        ForeignKey("buildings.building_id"), nullable=False, index=True
    )
    staff_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    shift_start: Mapped[time] = mapped_column(Time, nullable=False)
    shift_end: Mapped[time] = mapped_column(Time, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BackgroundJob(Base):
    """唯一调度表，语义与 app/worker/registry.py 的 SQL 对齐。"""

    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {_JOB_STATUS}", name="ck_background_jobs_status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    business_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
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
    scope_student_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class Reservation(Base):
    """一晚一条（student_id, service_date 唯一）：R05 唯一、R06 自动通过、R07 无限改期。

    `student_id` 不加外键：预约要能在目录尚未同步的学生上先落地，且 B 的 `pass_codes`
    同样只按 ID 引用预约，两边都不依赖对方的建表顺序。
    """

    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("student_id", "service_date", name="uq_reservations_student_night"),
        CheckConstraint(f"status IN {_RESERVATION_STATUS}", name="ck_reservations_status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    school_id: Mapped[str] = mapped_column(String(40), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    planned_return_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReservationRevision(Base):
    """修订历史只追加，取消后恢复同一预约 ID 时同样落一条 RESTORE（R07）。"""

    __tablename__ = "reservation_revisions"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id", "version", "source", name="uq_reservation_revisions_version"
        ),
        CheckConstraint(f"source IN {_REVISION_SOURCES}", name="ck_reservation_revisions_source"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    planned_return_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    changed_by: Mapped[str | None] = mapped_column(String(40))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Notification(Base):
    """模拟收件箱：一条 = 一个收件人的一份正文，重复投递由 (recipient_user_id, business_key) 拦住。

    工号账号 `source=STAFF_LOCAL` 没有邮箱，同一事件只落这一行、不生成邮件任务（R18、R19）。
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id", "business_key", name="uq_notifications_recipient_business_key"
        ),
        CheckConstraint(f"template IN {_NOTIFICATION_TEMPLATES}", name="ck_notifications_template"),
        CheckConstraint(f"channel IN {_NOTIFICATION_CHANNELS}", name="ck_notifications_channel"),
        CheckConstraint(f"status IN {_NOTIFICATION_STATUS}", name="ck_notifications_status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    business_key: Mapped[str] = mapped_column(String(200), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("background_jobs.id", ondelete="SET NULL"), index=True
    )
    template: Mapped[str] = mapped_column(String(24), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    recipient_email: Mapped[str | None] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    service_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="SENT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdentitySession(Base):
    __tablename__ = "identity_sessions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VerificationSession(Base):
    __tablename__ = "verification_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(40), nullable=False)
    student_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reservation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    face_result: Mapped[bool] = mapped_column(Boolean, nullable=False)
    presence_result: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pass_id: Mapped[str | None] = mapped_column(String(32))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PassageAttempt(Base):
    __tablename__ = "passage_attempts"
    __table_args__ = (UniqueConstraint("pass_id", name="uq_attempt_pass"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pass_id: Mapped[str] = mapped_column(String(32), nullable=False)
    device_id: Mapped[str] = mapped_column(String(32), nullable=False)
    student_id: Mapped[str] = mapped_column(String(32), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mock_result: Mapped[str] = mapped_column(String(16), nullable=False, default="SUCCEEDED")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessReceipt(Base):
    __tablename__ = "access_receipts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    attempt_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReturnCorrection(Base):
    __tablename__ = "return_corrections"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    return_id: Mapped[str] = mapped_column(ForeignKey("return_records.return_id"), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(String(500), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportSubscription(Base):
    __tablename__ = "report_subscriptions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    daily: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weekly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (UniqueConstraint("student_id", "service_date", "rule_version", name="uq_risk_event_fact"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(32), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskAction(Base):
    __tablename__ = "risk_actions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("risk_events.id"), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReturnEvidence(Base):
    __tablename__ = "return_evidence"
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    return_id: Mapped[str] = mapped_column(ForeignKey("return_records.return_id",ondelete="CASCADE"),nullable=False)
    source_key: Mapped[str] = mapped_column(String(160),nullable=False,unique=True)
    kind: Mapped[str] = mapped_column(String(16),nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB,nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False)
