"""风险只依据明确规则与正式返宿事实；不读取超时或未确认状态作为触发器。"""
import secrets
from datetime import datetime,timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from app.core.clock import business_iso,summary_moment
from app.core.db import get_engine
from app.core.errors import ApiError
from app.core.audit import append as audit
from app.db.models import RiskEvent,RiskAction
from app.modules.identity.schemas import Role
from app.modules.identity import service as identity
from app.modules.directory import service as directory
from app.modules.returns import service as returns
from app.modules.risk import rules


def view(row):
    return {"id":row.id,"student_id":row.student_id,"service_date":row.service_date.isoformat(),"status":row.status,
            "rule_version":row.rule_version,"facts":row.facts,"created_at":business_iso(row.created_at),"updated_at":business_iso(row.updated_at)}


def allowed(context,row):
    if context.active_role is Role.CAMPUS:return True
    if context.active_role in (Role.COUNSELOR,Role.IDEOLOGY,Role.COLLEGE_ADMIN):
        return row.student_id in context.scope.get("student_ids",[])
    if context.active_role is Role.DORM_MANAGER:
        home=directory.get_residence(row.student_id,summary_moment(row.service_date,datetime.fromisoformat(context.expires_at).tzinfo))
        return home is not None and home["building_id"] in context.scope.get("building_ids",[])
    return False


def list_events(db,context,status=None):
    if status and status not in ("OPEN","ACKNOWLEDGED","RESOLVED"):raise ApiError(422,"VALIDATION_FAILED","未知风险状态。",{})
    rows=db.scalars(select(RiskEvent).order_by(RiskEvent.created_at.desc(),RiskEvent.id))
    items=[]
    for row in rows:
        if (status and row.status!=status) or not allowed(context,row):continue
        item=view(row)
        item['actions']=[{'id':a.id,'actor_user_id':a.actor_user_id,'action':a.action,'note':a.note,'created_at':business_iso(a.created_at)} for a in db.scalars(select(RiskAction).where(RiskAction.event_id==row.id).order_by(RiskAction.created_at,RiskAction.id))]
        items.append(item)
    return {"items":items,"next_cursor":None}


def act(db,context,event_id,action,note,at):
    row=db.get(RiskEvent,event_id,with_for_update=True)
    if row is None or not allowed(context,row):raise ApiError(404,"SUBJECT_NOT_FOUND","事件不存在或不在负责范围。",{})
    if not note.strip() or len(note)>500:raise ApiError(422,"VALIDATION_FAILED","跟进说明需要 1—500 字符。",{})
    target="ACKNOWLEDGED" if action=="ACK" else "RESOLVED"
    if row.status==target:return view(row)
    if row.status=="RESOLVED":raise ApiError(409,"VERSION_CONFLICT","事件已解决。",{})
    row.status=target;row.updated_at=at
    db.add(RiskAction(id="ract_"+secrets.token_hex(12),event_id=row.id,actor_user_id=context.user_id,action=action,note=note,created_at=at))
    audit(db,context.user_id,"RISK_"+action,event_id,{"note":note},at);db.commit();return view(row)


def evaluate_all(db,clock,night):
    rule=rules.current_rule_set();at=clock.now();created=0
    facts=returns.fact_nights(night-timedelta(days=rule.window_nights-1),night)
    for student_id,nights in facts.items():
        result=rules.evaluate(nights,tonight=night,rules=rule)
        if not result.crossed:continue
        recipients=set(directory.get_counselors(student_id,at))
        home=directory.get_residence(student_id,at)
        if home:recipients.update(directory.get_duty_staff(home["building_id"],at))
        recipients={u for u in recipients if (p:=identity.person_by_user_id(u)) and Role.CAMPUS not in p.roles and bool(set(p.roles)&{Role.COUNSELOR,Role.IDEOLOGY,Role.DORM_MANAGER})}
        event_id="risk_"+secrets.token_hex(12)
        detail={"basis":"FORMAL_RETURNS","times":result.times,"consecutive_nights":result.consecutive_nights,"window_nights":result.window_nights,"nights":[d.isoformat() for d in result.nights]}
        inserted=db.execute(insert(RiskEvent).values(id=event_id,student_id=student_id,service_date=night,rule_version=rule.version,status="OPEN",facts=detail,recipients=sorted(recipients),created_at=at,updated_at=at).on_conflict_do_nothing(index_elements=["student_id","service_date","rule_version"]).returning(RiskEvent.id)).scalar_one_or_none()
        if inserted is None:continue
        created+=1
        if recipients:
            from app.worker.scheduler import enqueue
            enqueue(db.connection(),"NOTIFICATION_SEND","risk-event:"+event_id,
                {"risk_event_id":event_id,"template":"RISK_ALERT","service_date":night.isoformat(),"recipient_user_ids":sorted(recipients)},at)
        else:audit(db,None,"RISK_RECIPIENT_MISSING",event_id,{"student_id":student_id},at)
    db.commit();return created


def notification(event_id,user_id,at):
    person=identity.person_by_user_id(user_id)
    if person is None or Role.CAMPUS in person.roles:return None
    from app.modules.identity.schemas import SessionContext
    with Session(get_engine()) as db:
        row=db.get(RiskEvent,event_id)
        if row is None or row.status=="RESOLVED" or user_id not in row.recipients:return None
        for role in person.roles:
            if role not in (Role.COUNSELOR,Role.IDEOLOGY,Role.DORM_MANAGER):continue
            ctx=SessionContext(session_id="internal",user_id=user_id,school_id=person.school_id,display_name=person.display_name,roles=person.roles,active_role=role,
                scope=identity.resolve_scope(person,role,at),expires_at=at.isoformat(),account_source=person.account_source)
            if allowed(ctx,row):return view(row)
    return None
