"""千人体验数据编排；合成目录，预约/返宿通过各自领域服务写入。"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.clock import Clock, build_clock, service_date_of
from app.core.config import get_settings
from app.db import seed as small
from app.db.models import (
    Building, CounselorAssignment, Device, DutyAssignment, Gate, Organization,
    Residence, RoleAssignment, Student, User,
)
from app.modules.reservation import service as reservations
from app.modules.returns import service as returns
from app.modules.verification import service as verification
from app.modules.access import service as access

STUDENT_COUNT = 1000
COLLEGES = small.COLLEGES + [("org_college_mech", "机械学院"), ("org_college_human", "人文学院")]
MAJORS = [("计算机科学", "软件工程"), ("数学", "统计学"), ("物理学", "应用物理"),
          ("机械工程", "工业设计"), ("汉语言文学", "历史学")]
GRADES = ("2023", "2024", "2025", "2026")
HISTORY_NIGHTS = 14


class ScenarioClock(Clock):
    def __init__(self, moment: datetime):
        super().__init__("Asia/Shanghai")
        self.moment = moment

    def now(self):
        return self.moment


def populate(engine, today: date, tz_name: str = "Asia/Shanghai"):
    """在空库中装载；调用者负责迁移、备份和显式重置。"""
    small.seed(engine, today, tz_name, with_history=False)
    tz = ZoneInfo(tz_name)
    at = small._local(today, 18, tz)
    with Session(engine) as db:
        db.add_all(Organization(org_id=oid, org_type="COLLEGE", name=name) for oid, name in COLLEGES[3:])
        db.flush()
        db.add(Building(building_id="bldg_a10", campus_org_id="campus_park_east4", name="A10 号楼", code="A10"))
        db.flush()
        for b in range(3, 11):
            db.add(Gate(gate_id=f"gate_a{b}_north", building_id=f"bldg_a{b}", name=f"A{b} 北门"))
        db.flush()
        for b in range(3, 11):
            db.add(Device(device_id=f"dev_synth_a{b}_01", gate_id=f"gate_a{b}_north", label=f"A{b} 北门模拟终端"))

        def teacher(uid, login, name, college, title):
            row = db.get(User, uid)
            if row is None:
                row = User(user_id=uid, school_id=f"SYN-{login}", login_name=login,
                           source="UNIFIED_SCHOOL", status="ACTIVE", identity_types=["TEACHER"], building_ids=[])
                db.add(row)
            row.display_name = name
            row.college_org_id = college
            row.position_title = title
            return row

        def grant(uid, role, scope):
            row = db.scalar(select(RoleAssignment).where(RoleAssignment.user_id == uid, RoleAssignment.role == role))
            if row is None:
                row = RoleAssignment(id=f"exp_{uid}_{role}"[:40], user_id=uid, role=role)
                db.add(row)
            row.scope = scope
            row.active = True

        students = []
        student_buildings = {}
        bed_counts = {}
        for i in range(STUDENT_COUNT):
            n = i + 1
            college = i // 200
            class_index = i % 200 // 25
            grade = GRADES[class_index // 2]
            building = 1 if i < 12 else (2 if i < 24 else (i - 24) % 10 + 1)
            student = db.get(Student, f"stu_synth_{n:04d}") or Student(student_id=f"stu_synth_{n:04d}")
            student.school_id = f"{grade}S{n:04d}"
            student.display_name = f"合成学生{n:04d}"
            student.college_org_id = COLLEGES[college][0]
            student.grade = grade
            student.major = MAJORS[college][class_index % 2]
            student.class_name = f"{grade}级{student.major}1班"
            student.gender = "MALE" if building % 2 else "FEMALE"
            student.phone = f"SYN-PHONE-{n:04d}"
            uid = "usr_synth_0001" if i == 0 else ("usr_synth_0002" if i == 8 else f"usr_exp_s{n:04d}")
            if i != 8:
                user = db.get(User, uid)
                if user is None:
                    user = User(user_id=uid, login_name=f"student_{n:04d}", source="UNIFIED_SCHOOL",
                                status="ACTIVE", identity_types=["STUDENT"], building_ids=[], position_title="学生")
                    db.add(user)
                user.school_id = student.school_id
                user.display_name = student.display_name
                user.college_org_id = student.college_org_id
            db.flush()
            student.user_id = uid
            student_buildings[student.student_id] = building
            db.add(student)
            db.flush()
            residence = db.scalar(select(Residence).where(Residence.student_id == student.student_id))
            if residence is None:
                residence = Residence(residence_id=f"res_{student.student_id}", student_id=student.student_id, valid_from=small.RESIDENCE_START)
                db.add(residence)
            residence.building_id = f"bldg_a{building}"
            # 四人间，同楼同房最多四人；首批固定 ID 也进入统一房间编排。
            room_index = bed_counts.get(building, 0) // 4
            bed_counts[building] = bed_counts.get(building, 0) + 1
            residence.room_no = f"A{building}-{room_index // 20 + 1}{room_index % 20 + 1:02d}"
            students.append(student)

        db.execute(delete(CounselorAssignment))
        for c, (oid, name) in enumerate(COLLEGES):
            admin = "usr_synth_0007" if c == 0 else f"usr_exp_admin{c}"
            teacher(admin, "college_admin" if c == 0 else f"college_admin_{c+1}", f"合成{name}负责人", oid, "学院总负责人")
            db.flush()
            grant(admin, "COLLEGE_ADMIN", {"college_org_ids": [oid]})
            for k in range(4):
                uid = "usr_synth_0002" if c == 0 and k == 0 else ("usr_synth_0009" if c == 0 and k == 1 else f"usr_exp_c{c}_{k}")
                login = "counselor" if uid == "usr_synth_0002" else ("part_time_counselor" if uid == "usr_synth_0009" else f"counselor_{c+1}_{k+1}")
                teacher(uid, login, f"合成{name}辅导员{k+1}", oid, "兼任辅导员")
                assigned = students[c*200+k*50:c*200+(k+1)*50]
                db.flush()
                grant(uid, "COUNSELOR", {"student_ids": [s.student_id for s in assigned]})
                db.add_all(CounselorAssignment(assignment_id=f"exp_ca_{s.student_id}", counselor_user_id=uid,
                                             student_id=s.student_id, valid_from=small.RESIDENCE_START) for s in assigned)
            uid = "usr_synth_0005" if c == 0 else f"usr_exp_i{c}"
            teacher(uid, "ideology" if c == 0 else f"ideology_{c+1}", f"合成{name}思政教师", oid, "专职思政教师")
            assigned = students[c*200:c*200+40]
            db.flush()
            grant(uid, "IDEOLOGY", {"student_ids": [s.student_id for s in assigned]})
            db.add_all(CounselorAssignment(assignment_id=f"exp_ci_{s.student_id}", counselor_user_id=uid,
                                         student_id=s.student_id, valid_from=small.RESIDENCE_START) for s in assigned)
        db.execute(delete(DutyAssignment))
        for b in range(1, 11):
            for shift in ("day", "night"):
                uid = "usr_synth_0003" if b == 1 and shift == "night" else f"usr_exp_d{b}_{shift}"
                staff = db.get(User, uid)
                if staff is None:
                    staff = User(user_id=uid, school_id=f"SYN-W{b:02d}-{shift}", login_name=f"dorm_a{b}_{shift}",
                                 source="STAFF_LOCAL", identity_types=["EMPLOYEE"], status="ACTIVE")
                    db.add(staff)
                staff.display_name = f"合成A{b}楼{'白班' if shift=='day' else '夜班'}阿姨"
                staff.password = get_settings().demo_login_password
                staff.building_ids = [f"bldg_a{b}"]
                db.flush()
                for offset in range(-HISTORY_NIGHTS, small.DUTY_WINDOW_AFTER + 1):
                    night = today + timedelta(days=offset)
                    start = small._local(night, 6 if shift == "day" else 18, tz)
                    db.add(DutyAssignment(duty_id=f"exp_d{b}_{shift}_{night}", staff_user_id=uid,
                                          building_id=f"bldg_a{b}", service_date=night,
                                          shift_start=start, shift_end=start+timedelta(hours=12), is_substitute=False))
        # 原固定账号继续演示跨楼栋代班；23:00 起生效。
        db.add(DutyAssignment(duty_id="exp_substitute", staff_user_id="usr_synth_0003", building_id="bldg_a2",
                              service_date=today, shift_start=small._local(today, 23, tz),
                              shift_end=small._local(today+timedelta(days=1), 6, tz), is_substitute=True))
        db.commit()
        identities = [(s.student_id, s.school_id, s.user_id) for s in students]

    # 所有历史均沿生产领域函数，含修订、outbox 及返宿证据；不伪造已扫码标记。
    for offset in range(HISTORY_NIGHTS, -1, -1):
        night = today - timedelta(days=offset)
        clock = ScenarioClock(small._local(night, 20, tz))
        with Session(engine) as db:
            for i, (sid, school_id, uid) in enumerate(identities):
                if offset == 0 and i == 0:
                    continue  # 主学生账号留给体验者亲自预约。
                # 约 10% 日常预约；另有固定小群体连续预约，便于主动筛查。
                if (i + offset) % 10 != 0 and i % 100 not in (4, 5):
                    continue
                planned = small._local(night+timedelta(days=1), i % 5, tz, (i*7)%60)
                res = reservations.create_reservation(db, clock, student_id=sid, school_id=school_id,
                                                      actor_user_id=uid, planned_return_at=planned,
                                                      reason=("合成：实验课程", "合成：社团活动", "合成：返校交通")[i%3])
                args = dict(reservation_id=res.id, scope={"student_id":sid}, resolved_by="directory", actor_user_id=uid, expected_version=res.version)
                if i % 7 == 0:
                    reservations.cancel(db, clock, **args)
                    continue
                if i % 3 == 0:
                    reservations.reschedule(db, clock, **args, planned_return_at=planned+timedelta(minutes=10), reason="合成：行程调整")
                if offset and i % 4 != 0:
                    if i % 2:
                        actual = res.planned_return_at
                        context = SimpleNamespace(scope={"student_id":sid}, user_id=uid)
                        issued = verification.verify(db, ScenarioClock(actual), context, res.id, res.version, True, True)
                        b = student_buildings[sid]
                        device = f"dev_synth_a{b}_01"
                        access.consume(device, f"dev_synth:{device}", issued["pass"]["token"], at=actual+timedelta(seconds=45))
                    else:
                        returns.confirm_return(db.connection(), sid, night, "MANUAL", {"synthetic":True,"scenario":"HISTORICAL_MANUAL"},
                                               planned+timedelta(minutes=12), f"exp:{night}:{sid}", recorded_at=planned+timedelta(minutes=15))
                        db.commit()
                elif offset == 1:
                    # 已领码未通行：到期、失败、未知三种情形都不等于正式返宿。
                    actual = res.planned_return_at
                    context = SimpleNamespace(scope={"student_id":sid}, user_id=uid)
                    issued = verification.verify(db, ScenarioClock(actual), context, res.id, res.version, True, True)
                    if i % 3:
                        b = student_buildings[sid]
                        device = f"dev_synth_a{b}_01"
                        access.consume(device, f"dev_synth:{device}", issued["pass"]["token"], at=actual+timedelta(seconds=45),
                                       result="FAILED" if i%3 == 1 else "UNKNOWN", reconcile_result="FAILED")
            # 无预约按门铃补录也有正式记录。
            if offset:
                sid, _, _ = identities[(offset*10+3)%STUDENT_COUNT]
                occurred = small._local(night+timedelta(days=1), 1, tz, 15)
                returns.confirm_return(db.connection(), sid, night, "MANUAL", {"synthetic":True,"scenario":"NO_RESERVATION"},
                                       occurred, f"exp:manual:{night}", recorded_at=occurred+timedelta(minutes=2))
                db.commit()
    with Session(engine) as db:
        reservations.close_finished_nights(db, ScenarioClock(at))
    access.cleanup_expired_passes(at)
    from app.modules.risk import events
    from app.modules.reports import subscriptions
    from app.modules.identity.schemas import Role
    with Session(engine) as db:
        events.evaluate_all(db, ScenarioClock(at), today-timedelta(days=1))
        campus_context = SimpleNamespace(active_role=Role.CAMPUS)
        for index, event in enumerate(events.list_events(db, campus_context)["items"]):
            if index % 3 == 0:
                continue
            student_index = int(event["student_id"].rsplit("_",1)[1])-1
            c, k = student_index//200, student_index%200//50
            uid = "usr_synth_0002" if c == k == 0 else ("usr_synth_0009" if c == 0 and k == 1 else f"usr_exp_c{c}_{k}")
            context = SimpleNamespace(active_role=Role.COUNSELOR, scope={"student_ids":[event["student_id"]]}, user_id=uid)
            events.act(db, context, event["id"], "ACK", "合成跟进：已了解情况", at)
            if index % 3 == 2:
                events.act(db, context, event["id"], "RESOLVE", "合成跟进：沟通完成", at)
        subscriptions.save(db, "usr_synth_0002", True, True, at)
        subscriptions.save(db, "usr_synth_0005", True, False, at)
    return {"students": STUDENT_COUNT, "colleges":len(COLLEGES), "buildings":10, "classes":40}


def main():
    parser = argparse.ArgumentParser(description="重置合成体验库并装载 1000 人场景；请先备份")
    parser.add_argument("--reset", action="store_true", required=True)
    parser.add_argument("--service-date")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("缺少 DATABASE_URL")
    engine = create_engine(settings.database_url)
    today = date.fromisoformat(args.service_date) if args.service_date else service_date_of(build_clock().now())
    small.reset(engine)
    print(populate(engine, today, settings.business_timezone))


if __name__ == "__main__":
    main()
