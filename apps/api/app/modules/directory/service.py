"""目录领域服务（B 主责）：住宿、负责关系、当班人员与楼栋范围。

跨模块只调用本文件的函数，不查 B 的表、不调 B 的 HTTP 接口（AGENTS.md）。
时间判定统一用 app.core.clock，业务日 D 的住宿取 D 当日生效的快照（R02、基线「发生时快照」）。
"""

from __future__ import annotations

from datetime import date, datetime
from contextlib import contextmanager
from contextvars import ContextVar

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

_DUTY_BUILDINGS_SQL=text("SELECT DISTINCT building_id FROM duty_assignments WHERE staff_user_id=:staff_user_id AND shift_start<=:at AND shift_end>:at ORDER BY building_id")

_DUTY_STAFF_SQL=text("SELECT DISTINCT staff_user_id FROM duty_assignments WHERE building_id=:building_id AND shift_start<=:at AND shift_end>:at ORDER BY staff_user_id")

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
    from app.modules.identity.staff_accounts import fixed_buildings,active_staff
    if not active_staff([staff_user_id]):return []
    with get_engine().connect() as conn:
        assigned=list(conn.execute(_DUTY_BUILDINGS_SQL,{"staff_user_id":staff_user_id,"at":at}).scalars())
    return sorted(set(assigned)|set(fixed_buildings(staff_user_id)))


def get_duty_staff(building_id: str, at: datetime) -> list[str]:
    from app.modules.identity.staff_accounts import fixed_staff,active_staff
    with get_engine().connect() as conn:
        assigned=list(conn.execute(_DUTY_STAFF_SQL,{"building_id":building_id,"at":at}).scalars())
    return sorted(set(active_staff(assigned))|set(fixed_staff(building_id)))


def is_on_duty(staff_user_id: str, building_id: str, at: datetime) -> bool:
    return building_id in get_duty_buildings(staff_user_id, at)


def get_contact(student_id: str, at: datetime) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            _CONTACT_SQL, {"student_id": student_id, "service_date": _night(at)}
        ).mappings().first()
    return dict(row) if row else None


def statistic_students(conn, night: date) -> dict[str, dict]:
    """目录拥有的统计维度，不让消费者自己连接目录表。"""
    rows = conn.execute(text("""
        SELECT s.student_id, s.college_org_id, s.gender, s.education_level, s.grade AS night_grade,
               s.grade AS enrolled_grade, h.building_id AS night_building_id,
               c.building_id AS current_building_id
        FROM students s
        LEFT JOIN residences h ON h.student_id=s.student_id AND h.valid_from<=:night AND (h.valid_to IS NULL OR h.valid_to>:night)
        LEFT JOIN residences c ON c.student_id=s.student_id AND c.valid_to IS NULL
    """), {"night": night}).mappings()
    return {r["student_id"]: dict(r) for r in rows}


def assert_buildings_exist(building_ids: list[str]) -> None:
    from app.core.errors import ApiError
    with get_engine().connect() as conn:
        known = set(conn.execute(text("SELECT building_id FROM buildings")).scalars())
    unknown = sorted(set(building_ids) - known)
    if unknown:
        raise ApiError(422, "VALIDATION_FAILED", "楼栋编号不存在。", {"building_ids": unknown})


def student_for_user(user_id):
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT student_id FROM students WHERE user_id=:u"),{"u":user_id}).scalar()


def students_in_colleges(college_ids):
    if not college_ids:return []
    with get_engine().connect() as conn:
        return list(conn.execute(text("SELECT student_id FROM students WHERE college_org_id=ANY(:ids) ORDER BY student_id"),{"ids":college_ids}).scalars())


def scope_facets(conn, student_ids):
    """给定学生集合，返回他们当前住宿涉及的学院/片区/楼栋/年级/培养层次。

    只用于把筛选目录收窄到调用者权限范围内；范围外的组织结构不出现在下拉里。
    培养层次为空的旧档案不计入层次选项，但仍计入「全部」。
    """
    facets = {"college_org_ids": set(), "park_org_ids": set(), "building_ids": set(), "grades": set(), "education_levels": set()}
    if not student_ids:
        return facets
    rows = conn.execute(text("""
        SELECT DISTINCT s.college_org_id, s.grade, s.education_level,
               res.building_id, b.campus_org_id AS park_org_id
        FROM students s
        LEFT JOIN residences res ON res.student_id=s.student_id AND res.valid_to IS NULL
        LEFT JOIN buildings b ON b.building_id=res.building_id
        WHERE s.student_id=ANY(:ids)
    """), {"ids": list(student_ids)}).mappings()
    for r in rows:
        if r["college_org_id"]: facets["college_org_ids"].add(r["college_org_id"])
        if r["park_org_id"]: facets["park_org_ids"].add(r["park_org_id"])
        if r["building_id"]: facets["building_ids"].add(r["building_id"])
        if r["grade"]: facets["grades"].add(r["grade"])
        if r["education_level"]: facets["education_levels"].add(r["education_level"])
    return facets


def student_directory(context, filters=None):
    filters=filters or {}
    with get_engine().connect() as conn:
        rows=[dict(r) for r in conn.execute(text("""
            SELECT s.student_id,s.school_id,s.display_name,s.college_org_id,o.name AS college_name,
                   s.grade,s.major,s.class_name,r.building_id
            FROM students s JOIN organizations o ON o.org_id=s.college_org_id
            LEFT JOIN residences r ON r.student_id=s.student_id AND r.valid_to IS NULL
            ORDER BY s.school_id
        """)).mappings()]
    role=context.active_role.value
    if role in ("COUNSELOR","IDEOLOGY","COLLEGE_ADMIN"):
        ids=set(context.scope.get("student_ids") or [])
        rows=[r for r in rows if r["student_id"] in ids]
    elif role=="STUDENT":rows=[r for r in rows if r["student_id"]==context.scope.get("student_id")]
    elif role not in ("AUTH_ADMIN","CAMPUS"):
        rows=[]
    for key in ("college_org_id","major","grade","class_name"):
        if filters.get(key):rows=[r for r in rows if r[key]==filters[key]]
    if filters.get("q"):
        q=filters["q"].casefold()
        rows=[r for r in rows if q in (r["school_id"]+r["display_name"]).casefold()]
    return rows


def student_colleges(student_ids):
    if not student_ids:return {}
    with get_engine().connect() as conn:
        return dict(conn.execute(text("SELECT student_id,college_org_id FROM students WHERE student_id=ANY(:ids)"),{"ids":student_ids}).tuples().all())


def set_responsibilities(conn, user_id, student_ids, at):
    """授权模块调用此出口，同事务改负责关系，不从别的模块直接写目录表。"""
    import secrets
    night=service_date_of(at)
    conn.execute(text("DELETE FROM counselor_assignments WHERE counselor_user_id=:u AND valid_from=:night"),{"u":user_id,"night":night})
    conn.execute(text("UPDATE counselor_assignments SET valid_to=:night WHERE counselor_user_id=:u AND (valid_to IS NULL OR valid_to>:night)"),{"u":user_id,"night":night})
    for sid in sorted(set(student_ids)):
        conn.execute(text("INSERT INTO counselor_assignments(assignment_id,counselor_user_id,student_id,valid_from) VALUES (:id,:u,:s,:n)"),{"id":"ca_"+secrets.token_hex(10),"u":user_id,"s":sid,"n":night})


_label_snapshot: ContextVar[dict | None] = ContextVar('directory_label_snapshot', default=None)


@contextmanager
def prefetched_labels(conn):
    """当前领域调用内批量读取标签；退出即释放，不跨请求缓存个人数据。"""
    labels = {r[0]: (r[1], r[2]) for r in conn.execute(text('SELECT student_id,school_id,display_name FROM students'))}
    token = _label_snapshot.set(labels)
    try:
        yield
    finally:
        _label_snapshot.reset(token)


def label_for(student_id):
    snapshot = _label_snapshot.get()
    if snapshot is not None:
        return snapshot.get(student_id)
    with get_engine().connect() as conn:
        row=conn.execute(text("SELECT school_id,display_name FROM students WHERE student_id=:s"),{"s":student_id}).first()
    return tuple(row) if row else None


def all_college_ids():
    with get_engine().connect() as conn:
        return set(conn.execute(text("SELECT org_id FROM organizations WHERE org_type='COLLEGE'")).scalars())


def snapshot_buildings(at):
    with get_engine().connect() as conn:
        return list(conn.execute(text("SELECT building_id FROM buildings ORDER BY building_id")).scalars())


def duty_rows():
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text("SELECT duty_id,staff_user_id,building_id,service_date,shift_start,shift_end,is_substitute FROM duty_assignments ORDER BY shift_start DESC" )).mappings()]


def assign_duty(conn,staff_user_id,building_id,start,end):
    import secrets
    from app.core.errors import ApiError
    if end<=start:raise ApiError(422,"VALIDATION_FAILED","班次结束必须晚于开始。",{})
    assert_buildings_exist([building_id])
    duty_id="duty_"+secrets.token_hex(10)
    conn.execute(text("INSERT INTO duty_assignments(duty_id,staff_user_id,building_id,service_date,shift_start,shift_end,is_substitute) VALUES(:id,:u,:b,:d,:s,:e,true)"),{"id":duty_id,"u":staff_user_id,"b":building_id,"d":service_date_of(start),"s":start,"e":end})
    return {"duty_id":duty_id,"staff_user_id":staff_user_id,"building_id":building_id,"shift_start":start,"shift_end":end,"is_substitute":True}


def revoke_duty(conn,duty_id,at):
    from app.core.errors import ApiError
    row=conn.execute(text("SELECT * FROM duty_assignments WHERE duty_id=:id FOR UPDATE"),{"id":duty_id}).mappings().first()
    if row is None:raise ApiError(404,"SUBJECT_NOT_FOUND","指派不存在。",{})
    # 未来指派置零时长取消；既往指派保留历史区间。
    conn.execute(text("UPDATE duty_assignments SET shift_end=GREATEST(shift_start,LEAST(shift_end,:at)) WHERE duty_id=:id"),{"at":at,"id":duty_id})
    return {"status":"REVOKED","duty_id":duty_id}


_ENROLLED_RANGE_SQL = text(
    """
    SELECT res.student_id,
           res.building_id,
           s.college_org_id,
           s.gender,
           s.education_level,
           s.grade,
           s.grade AS grade_key
    FROM residences res
    JOIN students s ON s.student_id = res.student_id
    WHERE CASE WHEN :snapshot
              THEN res.valid_from <= :date_to
                   AND (res.valid_to IS NULL OR res.valid_to >= :date_from)
              ELSE res.valid_to IS NULL
          END
    """
)

_ENROLLED_NIGHT_SQL = text(
    """
    SELECT res.student_id,
           res.building_id,
           s.college_org_id,
           s.gender,
           s.education_level,
           s.grade,
           s.grade AS grade_key
    FROM residences res
    JOIN students s ON s.student_id = res.student_id
    WHERE res.valid_from <= CAST(:night AS date)
      AND (res.valid_to IS NULL OR res.valid_to > CAST(:night AS date))
    """
)

_COLLEGES_SQL = text(
    "SELECT org_id, name FROM organizations WHERE org_type = 'COLLEGE' ORDER BY name, org_id"
)

_PARKS_SQL = text(
    """
    SELECT o.org_id, o.name, COUNT(b.building_id) AS building_count
    FROM organizations o
    LEFT JOIN buildings b ON b.campus_org_id = o.org_id
    WHERE o.org_type = 'CAMPUS_PARK'
    GROUP BY o.org_id, o.name
    ORDER BY o.org_id
    """
)

_BUILDINGS_SQL = text(
    """
    SELECT building_id, name, code, campus_org_id AS park_org_id
    FROM buildings
    ORDER BY code, building_id
    """
)

_GRADES_SQL = text("SELECT DISTINCT grade FROM students ORDER BY grade")


def enrolled_range(conn,start,end,attribution):
    return [dict(r) for r in conn.execute(_ENROLLED_RANGE_SQL,{"date_from":start,"date_to":end,"snapshot":attribution=="snapshot"}).mappings()]


def enrolled_night(conn,night):
    return [dict(r) for r in conn.execute(_ENROLLED_NIGHT_SQL,{"night":night}).mappings()]


def filter_catalog(conn):
    return {"colleges":[dict(r) for r in conn.execute(_COLLEGES_SQL).mappings()],"parks":[dict(r) for r in conn.execute(_PARKS_SQL).mappings()],"buildings":[dict(r) for r in conn.execute(_BUILDINGS_SQL).mappings()],"grades":list(conn.execute(_GRADES_SQL).scalars()),"education_levels":["BACHELOR","MASTER","DOCTORAL"],"genders":["MALE","FEMALE"],"return_sources":["QR","MANUAL"]}


def return_labels(conn,night):
    return {r["student_id"]:dict(r) for r in conn.execute(text("SELECT s.student_id,s.school_id,s.display_name,r.building_id FROM students s LEFT JOIN residences r ON r.student_id=s.student_id AND r.valid_from<=:n AND (r.valid_to IS NULL OR r.valid_to>:n)"),{"n":night}).mappings()}


def gate_names(conn):
    return dict(conn.execute(text("SELECT gate_id,name FROM gates")).all())


def device_binding(device_id):
    with get_engine().connect() as conn:
        row=conn.execute(text("SELECT d.device_id,d.token_digest,d.gate_id,g.building_id,g.name AS gate_name FROM devices d JOIN gates g ON g.gate_id=d.gate_id WHERE d.device_id=:id"),{"id":device_id}).mappings().first()
        return dict(row) if row else None
