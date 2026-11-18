"""目录领域服务（B 主责）：住宿、负责关系、当班人员与楼栋范围。

跨模块只调用本文件的函数，不查 B 的表、不调 B 的 HTTP 接口（AGENTS.md）。
时间判定统一用 app.core.clock，业务日 D 的住宿取 D 当日生效的快照（R02、基线「发生时快照」）。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text

from app.core.clock import service_date_of
from app.core.db import get_engine

_RESIDENCE_SQL = text(
    """
    SELECT r.building_id,
           r.room_no,
           b.campus_org_id,
           park.name AS park_name,
           s.school_id,
           s.display_name,
           s.college_org_id,
           o.name AS college_name,
           s.grade,
           s.gender,
           s.phone
    FROM residences r
    JOIN students s ON s.student_id = r.student_id
    JOIN buildings b ON b.building_id = r.building_id
    JOIN organizations o ON o.org_id = s.college_org_id
    JOIN organizations park ON park.org_id = b.campus_org_id
    WHERE r.student_id = :student_id
      AND r.valid_from <= :service_date
      AND (r.valid_to IS NULL OR r.valid_to > :service_date)
    ORDER BY r.valid_from DESC
    LIMIT 1
    """
)

_BUILDING_RESIDENTS_SQL = text(
    """
    SELECT s.student_id,
           s.school_id,
           s.display_name,
           r.room_no,
           s.college_org_id,
           o.name AS college_name,
           s.grade,
           s.gender
    FROM residences r
    JOIN students s ON s.student_id = r.student_id
    JOIN organizations o ON o.org_id = s.college_org_id
    WHERE r.building_id = :building_id
      AND r.valid_from <= :service_date
      AND (r.valid_to IS NULL OR r.valid_to > :service_date)
    ORDER BY r.room_no, s.school_id
    """
)

_COUNSELORS_SQL = text(
    """
    SELECT counselor_user_id
    FROM counselor_assignments
    WHERE student_id = :student_id
      AND valid_from <= :service_date
      AND (valid_to IS NULL OR valid_to > :service_date)
    """
)

_ASSIGNED_STUDENTS_SQL = text(
    """
    SELECT student_id
    FROM counselor_assignments
    WHERE counselor_user_id = :counselor_user_id
      AND valid_from <= :service_date
      AND (valid_to IS NULL OR valid_to > :service_date)
    ORDER BY student_id
    """
)

_DUTY_BUILDINGS_SQL = text(
    """
    SELECT DISTINCT building_id
    FROM duty_assignments
    WHERE staff_user_id = :staff_user_id
      AND shift_start <= :at
      AND shift_end > :at
    ORDER BY building_id
    """
)

_DUTY_STAFF_SQL = text(
    """
    SELECT DISTINCT staff_user_id
    FROM duty_assignments
    WHERE building_id = :building_id
      AND shift_start <= :at
      AND shift_end > :at
    ORDER BY staff_user_id
    """
)

_CONTACT_SQL = text(
    """
    SELECT s.student_id,
           s.school_id,
           s.display_name,
           s.phone,
           s.grade,
           s.gender,
           o.name AS college_name,
           r.building_id,
           r.room_no
    FROM students s
    JOIN residences r ON r.student_id = s.student_id
    JOIN organizations o ON o.org_id = s.college_org_id
    WHERE s.student_id = :student_id
      AND r.valid_from <= :service_date
      AND (r.valid_to IS NULL OR r.valid_to > :service_date)
    ORDER BY r.valid_from DESC
    LIMIT 1
    """
)


def _night(at: datetime) -> date:
    return service_date_of(at)


def get_residence(student_id: str, at: datetime) -> dict | None:
    """学生在业务夜的住宿快照；缺失时返回 None，由调用方判定配置异常。"""
    with get_engine().connect() as conn:
        row = conn.execute(
            _RESIDENCE_SQL, {"student_id": student_id, "service_date": _night(at)}
        ).mappings().first()
    return dict(row) if row else None


def list_building_residents(building_id: str, at: datetime) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            _BUILDING_RESIDENTS_SQL, {"building_id": building_id, "service_date": _night(at)}
        ).mappings().all()
    return [dict(r) for r in rows]


def search_building_residents(
    building_id: str, query: str | None, at: datetime
) -> list[dict]:
    """现场补录用：在本楼栋当晚名册里按姓名或学号子串锁定学生身份（R11）。

    名册只出身份不含联系方式；`org_id` 与 `college_org_id` 是内部字段，去掉后返回。
    `query` 留空返回全量，命中同时匹配姓名与学号，按学号升序。
    """
    residents = list_building_residents(building_id, at)
    needle = (query or "").strip().lower()
    matched = [
        resident
        for resident in residents
        if not needle
        or needle in str(resident["display_name"]).lower()
        or needle in str(resident["school_id"]).lower()
    ]
    matched.sort(key=lambda resident: str(resident["school_id"]))
    return [
        {
            "student_id": resident["student_id"],
            "school_id": resident["school_id"],
            "display_name": resident["display_name"],
            "building_id": building_id,
            "room_no": resident["room_no"],
            "college_name": resident["college_name"],
            "grade": resident.get("grade"),
            "gender": resident.get("gender"),
        }
        for resident in matched
    ]


def get_counselors(student_id: str, at: datetime) -> list[str]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            _COUNSELORS_SQL, {"student_id": student_id, "service_date": _night(at)}
        ).scalars().all()
    return list(rows)


def get_assigned_students(counselor_user_id: str, at: datetime) -> list[str]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            _ASSIGNED_STUDENTS_SQL,
            {"counselor_user_id": counselor_user_id, "service_date": _night(at)},
        ).scalars().all()
    return list(rows)


def get_duty_buildings(staff_user_id: str, at: datetime) -> list[str]:
    """只在值班区间内成立：23:00 代班生效前看不到 bldg_a2，失效后同样拒绝（R11）。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            _DUTY_BUILDINGS_SQL, {"staff_user_id": staff_user_id, "at": at}
        ).scalars().all()
    return list(rows)


def get_duty_staff(building_id: str, at: datetime) -> list[str]:
    """通知收件人解析：某楼栋此刻的当班人员（含代班）。"""
    with get_engine().connect() as conn:
        rows = conn.execute(_DUTY_STAFF_SQL, {"building_id": building_id, "at": at}).scalars().all()
    return list(rows)


def is_on_duty(staff_user_id: str, building_id: str, at: datetime) -> bool:
    return building_id in get_duty_buildings(staff_user_id, at)


def get_contact(student_id: str, at: datetime) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            _CONTACT_SQL, {"student_id": student_id, "service_date": _night(at)}
        ).mappings().first()
    return dict(row) if row else None
