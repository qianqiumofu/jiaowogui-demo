"""工作职责及其授权范围的唯一读写出口；基础身份由 identity.school 提供。"""
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_engine
from app.db.models import RoleAssignment


def grants_for(user_id):
    with Session(get_engine()) as db:
        return [{"id":r.id,"user_id":r.user_id,"role":r.role,"active":r.active,**r.scope}
                for r in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id==user_id, RoleAssignment.active.is_(True)).order_by(RoleAssignment.role))]


def scope_for(user_id, role):
    return next((r for r in grants_for(user_id) if r["role"]==role), {})


def active_users(role):
    with Session(get_engine()) as db:
        return list(db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.role==role,RoleAssignment.active.is_(True))))
