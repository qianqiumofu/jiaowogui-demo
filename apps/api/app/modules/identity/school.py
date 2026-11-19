"""模拟学校统一身份目录。认证只确认是谁，职责来自持久授权。"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_engine
from app.db.models import User
from app.modules.identity.schemas import Person, Role, AccountSource
from app.modules.authorization.roles import grants_for


def person(user_id=None, login_name=None):
    with Session(get_engine()) as db:
        query = select(User).where(User.user_id==user_id) if user_id else select(User).where(User.login_name==login_name)
        row = db.scalar(query)
        if row is None or row.status != "ACTIVE":
            return None
        if row.source == "STAFF_LOCAL":
            from app.modules.identity.staff_accounts import to_person
            return to_person(row)
        from app.modules.directory.service import student_for_user
        student = student_for_user(row.user_id)
        kinds = row.identity_types or (["STUDENT"] if student else ["TEACHER"])
        assigned = [Role(g["role"]) for g in grants_for(row.user_id)]
        # 担任工作职责不能伪造基础学籍/教师身份。
        assigned = [r for r in assigned if (r is not Role.STUDENT or student) and (r not in (Role.COUNSELOR,Role.IDEOLOGY,Role.COLLEGE_ADMIN,Role.CAMPUS) or "TEACHER" in kinds)]
        if student and Role.STUDENT not in assigned: assigned.append(Role.STUDENT)
        if not assigned: assigned=[Role.TEACHER] if "TEACHER" in kinds else [Role.STUDENT]
        priority = [Role.AUTH_ADMIN,Role.COLLEGE_ADMIN,Role.IDEOLOGY,Role.COUNSELOR,Role.CAMPUS,Role.STUDENT,Role.TEACHER]
        assigned.sort(key=lambda role:priority.index(role))
        return Person(user_id=row.user_id,school_id=row.school_id,display_name=row.display_name,
                      login_name=row.login_name,roles=assigned,account_source=AccountSource.UNIFIED_SCHOOL,
                      email=f"{row.school_id}@synth.edu.cn",student_id=student,
                      identity_types=kinds,college_org_id=row.college_org_id,position_title=row.position_title)


def users():
    with Session(get_engine()) as db:
        return [{"user_id":r.user_id,"school_id":r.school_id,"login_name":r.login_name,
                 "display_name":r.display_name,"identity_types":r.identity_types,
                 "college_org_id":r.college_org_id,"position_title":r.position_title,"source":r.source}
                for r in db.scalars(select(User).where(User.status=="ACTIVE").order_by(User.login_name))]
