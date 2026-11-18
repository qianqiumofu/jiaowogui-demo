"""合成演示数据（B 主责）。全部为合成值，禁止真实姓名、学号、人脸与联系方式。

固定 ID 与场景约定见 docs/10-演示数据与账号.md：
闵行校区 9 个片区（西一—西五、东一—东四）；stu_synth_0001—0012 住 bldg_a1，0013—0024 住 bldg_a2，
0025 起每 6 人住 bldg_a3—bldg_a9；李辅导员负责 0001—0006；
王宿管每晚主值 bldg_a1，23:00 起代班 bldg_a2；其余楼栋只登记不排班（宿管范围仍只有 A1/A2）。
楼栋性别单一（男生/女生宿舍），A1/A3/A5/A7/A9 为 MALE，A2/A4/A6/A8 为 FEMALE。
默认再写入演示夜之前 `HISTORY_NIGHTS` 个业务夜的合成返宿历史，供园区端统计出真数字；
`--no-history` 可关闭（今晚名单与扫码闭环的主演示不依赖它）。

用法：`python -m app.db.seed`（重置并写入以演示时钟为起点的值班窗口）。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.clock import service_date_of, summary_moment
from app.db.base import Base
from app.db.models import (
    BackgroundJob,
    Building,
    CounselorAssignment,
    Device,
    DutyAssignment,
    Gate,
    Organization,
    Residence,
    ReturnRecord,
    Student,
    User,
)
from app.modules.returns import service as returns_service

COLLEGES = [
    ("org_college_cs", "计算机学院"),
    ("org_college_math", "数学学院"),
    ("org_college_phys", "物理学院"),
]
PARKS = [
    ("campus_park_west1", "西一区"),
    ("campus_park_west2", "西二区"),
    ("campus_park_west3", "西三区"),
    ("campus_park_west4", "西四区"),
    ("campus_park_west5", "西五区"),
    ("campus_park_east1", "东一区"),
    ("campus_park_east2", "东二区"),
    ("campus_park_east3", "东三区"),
    ("campus_park_east4", "东四区"),
]
# A1/A2 保留原有 ID 与园区归属串：两人的测试与交接文档都锚在这两栋（docs/10）。
BUILDINGS = [
    ("bldg_a1", "campus_park_east1", "A1 号楼", "A1"),
    ("bldg_a2", "campus_park_east1", "A2 号楼", "A2"),
    ("bldg_a3", "campus_park_west1", "A3 号楼", "A3"),
    ("bldg_a4", "campus_park_west2", "A4 号楼", "A4"),
    ("bldg_a5", "campus_park_west3", "A5 号楼", "A5"),
    ("bldg_a6", "campus_park_west4", "A6 号楼", "A6"),
    ("bldg_a7", "campus_park_west5", "A7 号楼", "A7"),
    ("bldg_a8", "campus_park_east2", "A8 号楼", "A8"),
    ("bldg_a9", "campus_park_east3", "A9 号楼", "A9"),
]
# 门点与终端只在演示主楼栋落地；其余片区楼栋只登记住宿，不排班、不签码。
GATES = [("gate_a1_north", "bldg_a1", "A1 北门"), ("gate_a2_north", "bldg_a2", "A2 北门")]
DEVICES = [("dev_synth_a1_01", "gate_a1_north", "A1 北门终端"), ("dev_synth_a2_01", "gate_a2_north", "A2 北门终端")]
DEMO_BUILDING_IDS = ("bldg_a1", "bldg_a2")

USERS = [
    ("usr_synth_0001", "2023S0001", "张三（学生）", "student"),
    ("usr_synth_0002", "T2001", "李辅导员", "counselor"),
    ("usr_synth_0003", "W3001", "王宿管", "dorm"),
    ("usr_synth_0004", "G4001", "赵园区", "campus"),
]

STUDENT_COUNT = 66
DEMO_STUDENT_COUNT = 24
EXTRA_PER_BUILDING = 6
MALE = "MALE"
FEMALE = "FEMALE"
# 一栋楼只住一种性别（男生/女生宿舍），A1/A3/A5/A7/A9 男生，A2/A4/A6/A8 女生。
GENDER_BY_BUILDING = {
    "bldg_a1": MALE,
    "bldg_a2": FEMALE,
    "bldg_a3": MALE,
    "bldg_a4": FEMALE,
    "bldg_a5": MALE,
    "bldg_a6": FEMALE,
    "bldg_a7": MALE,
    "bldg_a8": FEMALE,
    "bldg_a9": MALE,
}
GRADES = ["2023", "2024", "2025"]
RESIDENCE_START = date(2026, 9, 1)
DUTY_WINDOW_BEFORE = 1
DUTY_WINDOW_AFTER = 29

MAIN_SHIFT_START_HOUR = 18
SUBSTITUTE_START_HOUR = 23
NIGHT_END_HOUR = 6

# 园区统计演示用的历史晚归：只覆盖演示夜之前的整夜，不碰当晚主演示场景。
HISTORY_NIGHTS = 14
LATE_NIGHT_EVERY = 4
LATE_STUDENT_EVERY = 10
HISTORY_QR_HOUR = 1
HISTORY_MANUAL_HOUR = 0
HISTORY_MANUAL_MINUTE = 40


def _history_rows(
    students: list[Student], demo_night: date, tz: ZoneInfo, count: int = HISTORY_NIGHTS
) -> list[ReturnRecord]:
    """确定性晚归历史：每 LATE_NIGHT_EVERY 个学号取一夜，每夜 LATE_STUDENT_EVERY 人轮流。

    夜序从演示夜的前一夜往回数，`return_records` 里不出现演示夜本身，A 的当晚名单与
    报表测试才不会看到多出来的合成行。
    只落 `return_records`（B 唯一写入方的表），不伪造预约与通行码：A 的预约源还没落地，
    园区端 `reservations/unconfirmed` 两列保持 null 并登记 data_gaps。
    一学生一业务夜唯一，所以晚归夜数恒等于这里的记录条数。
    """
    history_nights = [demo_night - timedelta(days=offset + 1) for offset in range(count)]
    rows: list[ReturnRecord] = []
    for offset, night in enumerate(history_nights):
        for index, student in enumerate(students):
            if (index + offset) % LATE_STUDENT_EVERY != LATE_NIGHT_EVERY:
                continue
            is_manual = index % LATE_NIGHT_EVERY == 0
            hour = HISTORY_MANUAL_HOUR if is_manual else HISTORY_QR_HOUR
            minute = (index * 3 + offset * 7) % 60
            occurred_at = _local(night + timedelta(days=1), hour, tz, minute)
            rows.append(
                ReturnRecord(
                    # return_id 只有 32 位，用「夜序号 + 学号序号」保证唯一且短。
                    return_id=f"ret_hist_{offset + 1:02d}_{index + 1:03d}",
                    student_id=student.student_id,
                    service_date=night,
                    source=returns_service.SOURCE_MANUAL if is_manual else returns_service.SOURCE_QR,
                    pass_id=None,
                    gate_id=None,
                    occurred_at=occurred_at,
                    recorded_at=occurred_at,
                    evidence={"synthetic": True, "generator": "app.db.seed.history"},
                    idempotency_key=f"hist:{night.isoformat()}:{student.student_id}",
                )
            )
    return rows


def _student_slot(index: int) -> tuple[str, str]:
    """学生在册楼栋与寝室号：前 24 人维持 A1/A2 原编号，之后每 6 人进 A3—A9。"""
    if index < 12:
        return "bldg_a1", f"A1-{301 + index}"
    if index < DEMO_STUDENT_COUNT:
        return "bldg_a2", f"A2-{301 + index - 12}"
    extra = index - DEMO_STUDENT_COUNT
    building_index = extra // EXTRA_PER_BUILDING
    code = f"A{building_index + 3}"
    return f"bldg_{code.lower()}", f"{code}-{401 + extra % EXTRA_PER_BUILDING}"


def _student_row(index: int) -> tuple[Student, str, str]:
    number = index + 1
    grade = GRADES[index % len(GRADES)]
    building, room = _student_slot(index)
    gender = GENDER_BY_BUILDING[building]
    if index == 0:
        name = "张三（合成）"
    elif index == 8:
        name = "李辅导员（学生身份）"
    else:
        name = f"合成学生{number:02d}"
    student = Student(
        student_id=f"stu_synth_{number:04d}",
        school_id=f"{grade}S{number:04d}",
        user_id="usr_synth_0001" if index == 0 else ("usr_synth_0002" if index == 8 else None),
        display_name=name,
        college_org_id=COLLEGES[index % len(COLLEGES)][0],
        grade=grade,
        gender=gender,
        phone=f"1380000{number:04d}",
    )
    return student, building, room


def _local(night: date, hour: int, tz: ZoneInfo, minute: int = 0) -> datetime:
    return datetime.combine(night, time(hour, minute), tzinfo=tz)


def _duty_rows(tz: ZoneInfo, nights: list[date]) -> list[DutyAssignment]:
    rows: list[DutyAssignment] = []
    for night in nights:
        night_end = _local(night + timedelta(days=1), NIGHT_END_HOUR, tz)
        rows.append(
            DutyAssignment(
                duty_id=f"duty_a1_{night.isoformat()}",
                staff_user_id="usr_synth_0003",
                building_id=DEMO_BUILDING_IDS[0],
                service_date=night,
                shift_start=_local(night, MAIN_SHIFT_START_HOUR, tz),
                shift_end=night_end,
                is_substitute=False,
            )
        )
        rows.append(
            DutyAssignment(
                duty_id=f"duty_a2_{night.isoformat()}",
                staff_user_id="usr_synth_0003",
                building_id=DEMO_BUILDING_IDS[1],
                service_date=night,
                shift_start=_local(night, SUBSTITUTE_START_HOUR, tz),
                shift_end=night_end,
                is_substitute=True,
            )
        )
    return rows


def _snapshot_jobs(nights: list[date], tz: ZoneInfo) -> list[BackgroundJob]:
    jobs: list[BackgroundJob] = []
    for night in nights:
        for building_id in DEMO_BUILDING_IDS:
            jobs.append(
                BackgroundJob(
                    id=f"job_snapshot_{building_id}_{night.isoformat()}",
                    job_type="DORM_TONIGHT_SNAPSHOT",
                    business_key=f"DORM_TONIGHT_SNAPSHOT:{building_id}:{night.isoformat()}",
                    payload={"building_id": building_id, "service_date": night.isoformat()},
                    planned_at=summary_moment(night, tz),
                    status="PENDING",
                )
            )
    return jobs


def reset(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE TABLE {table.name} CASCADE"))


def seed(engine: Engine, today: date, tz_name: str, with_history: bool = True) -> list[date]:
    tz = ZoneInfo(tz_name)
    nights = [today + timedelta(days=offset) for offset in range(-DUTY_WINDOW_BEFORE, DUTY_WINDOW_AFTER + 1)]

    with Session(engine) as session:
        session.add_all([Organization(org_id=oid, org_type="COLLEGE", name=name) for oid, name in COLLEGES])
        session.add_all(
            [Organization(org_id=oid, org_type="CAMPUS_PARK", name=name) for oid, name in PARKS]
        )
        session.flush()
        session.add_all(
            [
                Building(building_id=bid, campus_org_id=cid, name=name, code=code)
                for bid, cid, name, code in BUILDINGS
            ]
        )
        session.flush()
        session.add_all([Gate(gate_id=gid, building_id=bid, name=name) for gid, bid, name in GATES])
        session.flush()
        session.add_all([Device(device_id=did, gate_id=gid, label=label) for did, gid, label in DEVICES])
        session.add_all(
            [User(user_id=uid, school_id=sid, display_name=name, login_name=login) for uid, sid, name, login in USERS]
        )
        session.flush()

        students: list[Student] = []
        residences: list[Residence] = []
        for index in range(STUDENT_COUNT):
            student, building, room = _student_row(index)
            students.append(student)
            session.add(student)
            residences.append(
                Residence(
                    residence_id=f"res_{student.student_id}",
                    student_id=student.student_id,
                    building_id=building,
                    room_no=room,
                    valid_from=RESIDENCE_START,
                )
            )
        session.flush()
        session.add_all(residences)
        session.add_all(
            [
                CounselorAssignment(
                    assignment_id=f"ca_{student.student_id}",
                    counselor_user_id="usr_synth_0002",
                    student_id=student.student_id,
                    valid_from=RESIDENCE_START,
                )
                for student in students[:6]
            ]
        )
        session.add_all(_duty_rows(tz, nights))
        session.add_all(_snapshot_jobs(nights, tz))
        if with_history:
            session.add_all(_history_rows(students, today, tz))
        session.commit()
    return nights


def main() -> None:
    parser = argparse.ArgumentParser(description="写入合成演示数据")
    parser.add_argument("--service-date", help="业务夜起点 YYYY-MM-DD，默认取演示时钟")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="不写入园区统计用的合成晚归历史（今晚名单与扫码闭环演示不受影响）",
    )
    args = parser.parse_args()

    from app.core.clock import build_clock
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("缺少 DATABASE_URL，请先在 apps/api/.env 配置。")
    engine = create_engine(settings.database_url, future=True)

    clock = build_clock()
    today = (
        date.fromisoformat(args.service_date)
        if args.service_date
        else service_date_of(clock.now())
    )
    reset(engine)
    nights = seed(engine, today, settings.business_timezone, with_history=not args.no_history)
    print(
        f"已重置并写入合成数据：值班窗口 {nights[0].isoformat()}—{nights[-1].isoformat()}"
        f"，晚归历史 {'关闭' if args.no_history else f'演示夜之前 {HISTORY_NIGHTS} 夜'}"
    )


if __name__ == "__main__":
    main()
