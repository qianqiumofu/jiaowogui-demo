"""校级/学院分层授权；不会让工作职责伪造基础学籍或教师身份。"""
import secrets
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.audit import append as audit
from app.db.models import RoleAssignment, AuditLog
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import Role, SessionContext
from app.modules.identity import school, persistence
from app.modules.directory import service as directory

router=APIRouter(prefix="/management",tags=["authorization"])
Guard=Annotated[SessionContext,Depends(require("permission:manage"))]
DB=Annotated[Session,Depends(get_session)]

class GrantRequest(BaseModel):
    user_id:str
    role:Role
    student_ids:list[str]=Field(default_factory=list)
    college_org_ids:list[str]=Field(default_factory=list)


def view(row):
    return {"id":row.id,"user_id":row.user_id,"role":row.role,"active":row.active,
            "student_ids":row.scope.get("student_ids",[]),"college_org_ids":row.scope.get("college_org_ids",[])}


def assert_target(context,target,role,student_ids,colleges):
    if target is None or target.account_source.value!="UNIFIED_SCHOOL" or "TEACHER" not in target.identity_types:
        raise ApiError(422,"VALIDATION_FAILED","只有学校确认的教师可以获授工作职责。",{})
    if role not in (Role.COUNSELOR,Role.IDEOLOGY,Role.COLLEGE_ADMIN,Role.CAMPUS):
        raise ApiError(403,"FORBIDDEN_ACTION","基础身份和校级管理权限不能经普通职责接口授予。",{})
    if context.active_role is Role.AUTH_ADMIN and (role is not Role.COLLEGE_ADMIN or student_ids):
        raise ApiError(403,"FORBIDDEN_ACTION","校级仅可任免学院负责人，具体教师职责与学生范围由学院负责人配置。",{})
    known=directory.student_colleges(student_ids)
    if len(known)!=len(set(student_ids)):
        raise ApiError(422,"VALIDATION_FAILED","部分学生编号不存在。",{})
    if context.active_role is Role.COLLEGE_ADMIN:
        own=set(context.scope.get("college_org_ids") or [])
        if role not in (Role.COUNSELOR,Role.IDEOLOGY) or target.college_org_id not in own or not set(known.values()).issubset(own):
            raise ApiError(403,"OUT_OF_SCOPE","学院负责人只能管理本学院教师和学生的负责职责。",{})
    if role is Role.COLLEGE_ADMIN:
        allowed=directory.all_college_ids()
        if not colleges or not set(colleges).issubset(allowed):
            raise ApiError(422,"VALIDATION_FAILED","学院管理职责必须指定有效学院。",{})


def assert_existing_responsibilities(context,target,at):
    if context.active_role is Role.COLLEGE_ADMIN:
        actual=directory.get_assigned_students(target.user_id,at)
        colleges=set(directory.student_colleges(actual).values())
        if not colleges.issubset(set(context.scope.get('college_org_ids') or [])):
            raise ApiError(403,'OUT_OF_SCOPE','该教师现有负责关系包含其他学院，请由相关学院协调调整。',{})


def managed_rows(guard,q=None,college_org_id=None,identity_type=None):
    rows=school.users()
    if guard.active_role is Role.COLLEGE_ADMIN:
        own=set(guard.scope.get("college_org_ids") or [])
        rows=[r for r in rows if r["college_org_id"] in own and "TEACHER" in r["identity_types"]]
    if college_org_id:rows=[r for r in rows if r["college_org_id"]==college_org_id]
    if q:rows=[r for r in rows if q.casefold() in (r["display_name"]+r["school_id"]+r["login_name"]).casefold()]
    if identity_type:rows=[r for r in rows if identity_type in r["identity_types"]]
    return rows


@router.get("/users")
def users(guard:Guard,q:str|None=None,college_org_id:str|None=None,identity_type:str|None=None):
    if identity_type is not None and identity_type not in ("TEACHER","STUDENT","EMPLOYEE"):
        raise ApiError(422,"VALIDATION_FAILED","未知基础身份筛选。",{})
    rows=managed_rows(guard,q,college_org_id,identity_type)
    for row in rows:
        p=school.person(user_id=row["user_id"])
        row["roles"]=[r.value for r in p.roles] if p else []
        row["student_id"]=p.student_id if p else None
    return {"items":rows,"next_cursor":None}


@router.get("/grants")
def grants(guard:Guard,db:DB,request:Request):
    allowed={u["user_id"] for u in managed_rows(guard)}
    items=[]
    for row in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id.in_(allowed)).order_by(RoleAssignment.id)):
        if guard.active_role is Role.AUTH_ADMIN and row.role != "COLLEGE_ADMIN":
            continue
        item=view(row)
        if row.active and row.role in ('COUNSELOR','IDEOLOGY') and 'student_ids' not in row.scope:
            item['student_ids']=directory.get_assigned_students(row.user_id,request.app.state.clock.now())
        items.append(item)
    return {"items":items,"next_cursor":None}


@router.post("/grants",status_code=201)
def grant(payload:GrantRequest,guard:Guard,db:DB,request:Request):
    target=school.person(user_id=payload.user_id)
    students=sorted(set(payload.student_ids));colleges=sorted(set(payload.college_org_ids))
    assert_target(guard,target,payload.role,students,colleges)
    assert_existing_responsibilities(guard,target,request.app.state.clock.now())
    row=db.scalar(select(RoleAssignment).where(RoleAssignment.user_id==payload.user_id,RoleAssignment.role==payload.role.value).with_for_update())
    if row is None:
        row=RoleAssignment(id="grant_"+secrets.token_hex(12),user_id=payload.user_id,role=payload.role.value)
        db.add(row)
    before=view(row) if row.scope is not None else None
    if before and guard.active_role is Role.COLLEGE_ADMIN:
        assert_target(guard,target,payload.role,before['student_ids'],before['college_org_ids'])
    row.scope={"student_ids":students,"college_org_ids":colleges};row.active=True;row.granted_by=guard.user_id;row.updated_at=request.app.state.clock.now()
    db.flush()
    if payload.role in (Role.COUNSELOR,Role.IDEOLOGY):
        other=list(db.scalars(select(RoleAssignment).where(RoleAssignment.user_id==payload.user_id,RoleAssignment.active.is_(True),RoleAssignment.role.in_(["COUNSELOR","IDEOLOGY"]))))
        combined=set(students)
        for item in other:combined.update(item.scope.get("student_ids",[]))
        directory.set_responsibilities(db.connection(),payload.user_id,list(combined),request.app.state.clock.now())
    audit(db,guard.user_id,"ROLE_GRANTED",payload.user_id,{"before":before,"after":view(row),"college_org_ids":colleges or ([target.college_org_id] if target.college_org_id else [])},request.app.state.clock.now())
    db.commit();persistence.drop(user_id=payload.user_id)
    return view(row)


@router.delete("/grants/{grant_id}")
def revoke(grant_id:str,guard:Guard,db:DB,request:Request):
    row=db.get(RoleAssignment,grant_id,with_for_update=True)
    if row is None:raise ApiError(404,"SUBJECT_NOT_FOUND","职责授予不存在。",{})
    target=school.person(user_id=row.user_id)
    assert_target(guard,target,Role(row.role),row.scope.get("student_ids",[]),row.scope.get("college_org_ids",[]))
    assert_existing_responsibilities(guard,target,request.app.state.clock.now())
    row.active=False;db.flush()
    if row.role in ("COUNSELOR","IDEOLOGY"):
        remaining=list(db.scalars(select(RoleAssignment).where(RoleAssignment.user_id==row.user_id,RoleAssignment.active.is_(True),RoleAssignment.role.in_(["COUNSELOR","IDEOLOGY"]))))
        ids={s for r in remaining for s in r.scope.get("student_ids",[])}
        directory.set_responsibilities(db.connection(),row.user_id,list(ids),request.app.state.clock.now())
    audit(db,guard.user_id,"ROLE_REVOKED",row.user_id,{"grant_id":row.id,"college_org_ids":[target.college_org_id] if target.college_org_id else []},request.app.state.clock.now())
    db.commit();persistence.drop(user_id=row.user_id)
    return {"status":"REVOKED","id":row.id}


@router.get("/audit")
def audit_logs(guard:Guard,db:DB):
    rows=list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)))
    if guard.active_role is Role.COLLEGE_ADMIN:
        own=set(guard.scope.get("college_org_ids") or [])
        rows=[r for r in rows if r.actor_user_id==guard.user_id or bool(own.intersection(r.payload.get("college_org_ids",[])))]
    return {"items":[{"id":r.id,"actor_user_id":r.actor_user_id,"action":r.action,"target":r.target,"payload":r.payload,"created_at":r.created_at.isoformat()} for r in rows],"next_cursor":None}
