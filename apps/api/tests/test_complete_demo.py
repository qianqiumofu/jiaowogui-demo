"""完整 Demo 的真实 PG 验收：身份分层、核验、回执、周期任务、撤权与审计。"""
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.db import get_engine
from app.db.models import BackgroundJob, RoleAssignment, VerificationSession, PassCode, RiskEvent, AuditLog
from app.modules.directory import service as directory
from app.modules.notification import handlers
from app.modules.risk import events
from app.worker.main import run_once
from app.worker.registry import claim_due_jobs, mark_failed, mark_succeeded
from tests.conftest import API, auth, token_for

TZ=ZoneInfo("Asia/Shanghai")
NIGHT=date(2026,11,15)
PLAN=datetime(2026,11,16,0,40,tzinfo=TZ)
pytestmark=pytest.mark.usefixtures("clean_db")

class DemoClock(Clock):
    def __init__(self):
        super().__init__("Asia/Shanghai")
        self.moment=datetime(2026,11,15,22,tzinfo=TZ)
    def now(self):return self.moment

@pytest.fixture()
def clock(client,monkeypatch,clean_db):
    clock=DemoClock();client.app.state.clock=clock;client.app.state.session_store._clock=clock
    monkeypatch.setattr(handlers,"build_clock",lambda:clock)
    monkeypatch.setattr("app.core.clock.build_clock",lambda:clock)
    # 各授权场景独立，恢复已知合成职责而不依赖前一个用例是否撤权。
    defaults={"usr_synth_0005":"IDEOLOGY","usr_synth_0006":"TEACHER","usr_synth_0007":"COLLEGE_ADMIN","usr_synth_0008":"AUTH_ADMIN"}
    with Session(get_engine()) as db:
        for user,role in defaults.items():
            db.execute(text("DELETE FROM role_assignments WHERE user_id=:u"),{"u":user})
            db.add(RoleAssignment(id="test_default_"+role,user_id=user,role=role,active=True,scope={"college_org_ids":["org_college_cs"]} if role=="COLLEGE_ADMIN" else {}))
        db.commit()
    return clock

def reserve(client,planned=PLAN):
    token=token_for(client,"student")
    response=client.post(f"{API}/reservations",headers=auth(token),json={"planned_return_at":planned.isoformat()})
    assert response.status_code==201,response.text
    return token,response.json()

def verify(client,clock,result=True):
    token,res=reserve(client)
    clock.moment=PLAN
    response=client.post(f"{API}/verification-sessions",headers=auth(token),json={"reservation_id":res["id"],"expected_version":res["version"],"face_result":result,"presence_result":True})
    return token,res,response

def scan(client,clock,token,result="SUCCEEDED",reconcile="SUCCEEDED"):
    return client.post(f"{API}/device/scan",headers={"x-device-id":"dev_synth_a1_01","x-device-token":"dev_synth:dev_synth_a1_01"},json={"code":token,"result":result,"reconcile_result":reconcile})

@pytest.mark.parametrize("login,role,kinds",[
    ("student","STUDENT",["STUDENT"]),("teacher","TEACHER",["TEACHER"]),
    ("counselor","COUNSELOR",["TEACHER","STUDENT"]),("ideology","IDEOLOGY",["TEACHER"]),("part_time_counselor","COUNSELOR",["TEACHER"]),
    ("college_admin","COLLEGE_ADMIN",["TEACHER"]),("auth_admin","AUTH_ADMIN",["TEACHER"]),
    ("campus","CAMPUS",["TEACHER"]),("dorm","DORM_MANAGER",["EMPLOYEE"]),
])
def test_all_identity_types_log_in_with_correct_work_duties(client,clock,login,role,kinds):
    token=token_for(client,login)
    me=client.get(f"{API}/me",headers=auth(token)).json()
    assert me["active_role"]==role
    assert me["identity_types"]==kinds
    assert me["account_source"]==("STAFF_LOCAL" if login=="dorm" else "UNIFIED_SCHOOL")
    if login=="teacher":
        assert client.get(f"{API}/risk-events",headers=auth(token)).status_code==403
        assert client.post(f"{API}/auth/role-switch",headers=auth(token),json={"role":"STUDENT"}).status_code==403

def test_college_manager_sees_only_college_and_can_filter_classes(client,clock):
    token=token_for(client,"college_admin")
    response=client.get(f"{API}/directory/students",headers=auth(token))
    assert response.status_code==200,response.text
    rows=response.json()["items"]
    assert rows and {r["college_org_id"] for r in rows}=={"org_college_cs"}
    target=rows[0]
    filtered=client.get(f"{API}/directory/students",headers=auth(token),params={k:target[k] for k in ("major","grade","class_name")}).json()["items"]
    assert filtered and all(all(r[k]==target[k] for k in ("major","grade","class_name")) for r in filtered)
    with get_engine().connect() as conn:
        assert len(rows)==conn.execute(text("SELECT count(*) FROM students WHERE college_org_id='org_college_cs'")).scalar()

def test_college_can_assign_teacher_and_revoke_cross_process_session(client,clock):
    dean=token_for(client,"college_admin")
    teacher_before=token_for(client,"teacher")
    students=client.get(f"{API}/directory/students",headers=auth(dean)).json()["items"]
    chosen=[s["student_id"] for s in students[:2]]
    granted=client.post(f"{API}/management/grants",headers=auth(dean),json={"user_id":"usr_synth_0006","role":"COUNSELOR","student_ids":chosen})
    assert granted.status_code==201,granted.text
    assert client.get(f"{API}/me",headers=auth(teacher_before)).status_code==401
    teacher=token_for(client,"teacher")
    own=client.get(f"{API}/directory/students",headers=auth(teacher)).json()["items"]
    assert {r["student_id"] for r in own}==set(chosen)
    # 另一应用实例从持久会话恢复，不依赖原进程的字典。
    from fastapi.testclient import TestClient
    from app.main import create_app
    other=create_app();other.state.clock=clock
    with TestClient(other) as second:
        assert second.get(f"{API}/me",headers=auth(teacher)).status_code==200
        assert client.delete(f"{API}/management/grants/{granted.json()['id']}",headers=auth(dean)).status_code==200
        assert second.get(f"{API}/me",headers=auth(teacher)).status_code==401
    logs=client.get(f"{API}/management/audit",headers=auth(dean)).json()["items"]
    assert {r["action"] for r in logs}>={"ROLE_GRANTED","ROLE_REVOKED"}

@pytest.mark.parametrize("login",["student","teacher","counselor","ideology","campus","dorm"])
def test_non_admin_cannot_grant_any_work_role(client,clock,login):
    response=client.post(f"{API}/management/grants",headers=auth(token_for(client,login)),json={"user_id":"usr_synth_0006","role":"COLLEGE_ADMIN","college_org_ids":["org_college_cs"]})
    assert response.status_code==403

def test_college_cannot_expand_to_another_college_or_create_root(client,clock):
    dean=token_for(client,"college_admin")
    with get_engine().connect() as conn:
        outside=conn.execute(text("SELECT student_id FROM students WHERE college_org_id<>'org_college_cs' LIMIT 1")).scalar()
    for payload in [
        {"user_id":"usr_synth_0006","role":"COUNSELOR","student_ids":[outside]},
        {"user_id":"usr_synth_0006","role":"AUTH_ADMIN"},
        {"user_id":"usr_synth_0001","role":"COUNSELOR","student_ids":["stu_synth_0001"]},
        {"user_id":"usr_synth_0006","role":"COLLEGE_ADMIN","college_org_ids":["org_college_cs"]},
    ]:
        response=client.post(f"{API}/management/grants",headers=auth(dean),json=payload)
        assert response.status_code in (403,422),response.text

def test_school_can_set_multiple_colleges_without_gaining_student_role(client,clock):
    root=token_for(client,"auth_admin")
    colleges=sorted(directory.all_college_ids())[:2]
    response=client.post(f"{API}/management/grants",headers=auth(root),json={"user_id":"usr_synth_0006","role":"COLLEGE_ADMIN","college_org_ids":colleges})
    assert response.status_code==201,response.text
    target=token_for(client,"teacher")
    me=client.get(f"{API}/me",headers=auth(target)).json()
    assert set(me["scope"]["college_org_ids"])==set(colleges)
    assert "STUDENT" not in me["roles"]
    assert client.get(f"{API}/risk-events",headers=auth(root)).status_code==403

@pytest.mark.parametrize("moment,expected",[
    (datetime(2026,11,16,0,9,59,tzinfo=TZ),409),
    (datetime(2026,11,16,0,10,tzinfo=TZ),201),
    (datetime(2026,11,16,1,10,tzinfo=TZ),201),
    (datetime(2026,11,16,1,10,1,tzinfo=TZ),409),
])
def test_actual_verification_window_endpoints(client,clock,moment,expected):
    token,res=reserve(client);clock.moment=moment
    response=client.post(f"{API}/verification-sessions",headers=auth(token),json={"reservation_id":res["id"],"expected_version":1,"face_result":True,"presence_result":True})
    assert response.status_code==expected,response.text
    with Session(get_engine()) as db:
        assert len(list(db.scalars(select(PassCode))))==(1 if expected==201 else 0)

def test_failed_verification_is_audited_without_a_pass(client,clock):
    _,_,response=verify(client,clock,False)
    assert response.status_code==422 and response.json()["code"]=="VERIFICATION_FAILED"
    with Session(get_engine()) as db:
        assert list(db.scalars(select(PassCode)))==[]
        proof=db.scalars(select(VerificationSession)).one()
        assert proof.status=="FAILED" and proof.consumed_at is None

def test_student_code_scan_self_record_and_secret_not_reissued(client,clock):
    student,res,response=verify(client,clock)
    assert response.status_code==201,response.text
    body=response.json();assert "<svg" in body["pass"]["qr_svg"]
    stored=client.get(f"{API}/verification-sessions/{body['verification_id']}",headers=auth(student)).json()
    assert stored["pass_state"]=="ALLOWED" and "token" not in str(stored)
    result=scan(client,clock,body["pass"]["token"])
    assert result.status_code==200,result.text
    own=client.get(f"{API}/return-records/self?service_date={NIGHT}",headers=auth(student))
    assert own.status_code==200 and {r["student_id"] for r in own.json()["items"]}=={"stu_synth_0001"}
    assert client.get(f"{API}/reservations/tonight",headers=auth(student)).json()["status"]=="FULFILLED"
    evidence=client.get(f"{API}/return-records/{result.json()['return_id']}/evidence",headers=auth(student))
    assert evidence.status_code==200 and len(evidence.json()["items"])==1

@pytest.mark.parametrize("mode,expected",[("FAILED",0),("UNKNOWN",1)])
def test_device_failure_or_unknown_does_not_fabricate_return(client,clock,mode,expected):
    student,_,response=verify(client,clock);assert response.status_code==201,response.text
    result=scan(client,clock,response.json()["pass"]["token"],mode)
    assert result.status_code==200 and result.json()["attempt_status"]==mode
    before=client.get(f"{API}/return-records/self?service_date={NIGHT}",headers=auth(student)).json()
    assert before["counters"]["returned"]==0
    clock.moment+=timedelta(seconds=16)
    run_once(clock,timedelta(seconds=60))
    after=client.get(f"{API}/return-records/self?service_date={NIGHT}",headers=auth(student)).json()
    assert after["counters"]["returned"]==expected
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM pass_codes WHERE status='ISSUED'")).scalar()==0

def test_async_receipt_authentication_replay_and_conflict(client,clock):
    _,_,response=verify(client,clock);assert response.status_code==201,response.text
    attempt=scan(client,clock,response.json()["pass"]["token"],"UNKNOWN").json()
    payload={"event_id":"receipt_synth_1","attempt_id":attempt["attempt_id"],"status":"SUCCEEDED","occurred_at":clock.now().isoformat()}
    headers={"x-device-id":"dev_synth_a1_01","x-device-token":"dev_synth:dev_synth_a1_01"}
    wrong={"x-device-id":"dev_synth_a2_01","x-device-token":"dev_synth:dev_synth_a2_01"}
    assert client.post(f"{API}/integrations/access/events",headers=wrong,json=payload).status_code==403
    one=client.post(f"{API}/integrations/access/events",headers=headers,json=payload)
    two=client.post(f"{API}/integrations/access/events",headers=headers,json=payload)
    assert one.status_code==two.status_code==200 and two.json()["duplicate"]
    assert one.json()["return_id"]==two.json()["return_id"]
    assert client.post(f"{API}/integrations/access/events",headers=headers,json={**payload,"status":"FAILED"}).status_code==409

def test_subscription_drives_automatic_report_without_risk_preference_coupling(client,clock):
    teacher=token_for(client,"counselor")
    saved=client.put(f"{API}/reports/subscriptions",headers=auth(teacher),json={"daily":True,"weekly":False})
    assert saved.status_code==200 and saved.json()=={"daily":True,"weekly":False}
    reserve(client)
    clock.moment=datetime(2026,11,16,9,tzinfo=TZ)
    run_once(clock,timedelta(seconds=60),schedule=True)
    run_once(clock,timedelta(seconds=60),schedule=True)
    inbox=client.get(f"{API}/notifications",headers=auth(teacher)).json()["items"]
    assert [r["template"] for r in inbox]==["DAILY_REPORT"]
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM background_jobs WHERE job_type='COUNSELOR_DAILY_REPORT' AND payload->>'service_date'='2026-11-15'")).scalar()==1

def test_formal_return_risk_is_scoped_and_never_pushes_to_campus(client,clock):
    from app.modules.returns.service import confirm_return
    for day in (12,13,14):
        with get_engine().begin() as conn:
            confirm_return(conn,"stu_synth_0001",date(2026,11,day),"MANUAL",{},datetime(2026,11,day+1,0,40,tzinfo=TZ),f"risk_synth:{day}")
    with Session(get_engine()) as db:
        assert events.evaluate_all(db,clock,date(2026,11,14))==1
        assert events.evaluate_all(db,clock,date(2026,11,14))==0
    run_once(clock,timedelta(seconds=60))
    teacher=token_for(client,"counselor");campus=token_for(client,"campus")
    listed=client.get(f"{API}/risk-events",headers=auth(teacher)).json()["items"]
    assert len(listed)==1 and listed[0]["facts"]["basis"]=="FORMAL_RETURNS"
    assert client.get(f"{API}/notifications",headers=auth(campus)).json()["items"]==[]
    assert client.post(f"{API}/risk-events/{listed[0]['id']}/ack",headers=auth(campus),json={"note":"不得处置"}).status_code==403
    ack=client.post(f"{API}/risk-events/{listed[0]['id']}/ack",headers=auth(teacher),json={"note":"已核实合成情况"})
    assert ack.status_code==200 and ack.json()["status"]=="ACKNOWLEDGED"
    # 冻结时钟下推进一刻，让 ACK 与 RESOLVE 的 created_at 不同；历史顺序按时刻排序才稳定（生产时钟本就前进）。
    clock.moment=clock.moment+timedelta(minutes=1)
    resolved=client.post(f"{API}/risk-events/{listed[0]['id']}/resolve",headers=auth(teacher),json={"note":"已完成合成跟进"})
    assert resolved.status_code==200 and resolved.json()["status"]=="RESOLVED"
    history=client.get(f'{API}/risk-events',headers=auth(teacher)).json()['items'][0]['actions']
    assert [a['action'] for a in history]==['ACK','RESOLVE']
    assert history[-1]['note']=='已完成合成跟进'

def test_campus_assigns_substitute_but_dorm_cannot_self_expand(client,clock):
    campus=token_for(client,"campus");dorm=token_for(client,"dorm")
    payload={"staff_user_id":"usr_synth_0003","building_id":"bldg_a2","shift_start":"2026-11-15T22:30:00+08:00","shift_end":"2026-11-15T23:30:00+08:00"}
    assert client.post(f"{API}/duty-assignments",headers=auth(dorm),json=payload).status_code==403
    assigned=client.post(f"{API}/duty-assignments",headers=auth(campus),json=payload)
    assert assigned.status_code==201,assigned.text
    clock.moment=datetime(2026,11,15,22,31,tzinfo=TZ)
    assert "bldg_a2" in client.get(f"{API}/me",headers=auth(dorm)).json()["scope"]["building_ids"]
    assert client.delete(f"{API}/duty-assignments/{assigned.json()['duty_id']}",headers=auth(campus)).status_code==200
    assert "bldg_a2" not in client.get(f"{API}/me",headers=auth(dorm)).json()["scope"]["building_ids"]

def test_lease_recovery_fences_old_worker_and_applies_retry_backoff(client,clock):
    from app.worker.scheduler import enqueue
    with get_engine().begin() as conn:enqueue(conn,"TEST_SYNTH","lease_synth",{},clock.now())
    first=claim_due_jobs(clock.now(),timedelta(seconds=10))[0]
    clock.moment+=timedelta(seconds=11)
    second=claim_due_jobs(clock.now(),timedelta(seconds=10))[0]
    assert first["attempts"]==1 and second["attempts"]==2
    mark_succeeded(first["id"],clock.now(),first["attempts"])
    with get_engine().connect() as conn:assert conn.execute(text("SELECT status FROM background_jobs WHERE id=:id"),{"id":first["id"]}).scalar()=="RUNNING"
    mark_failed(second["id"],"合成失败",clock.now(),second["attempts"])
    assert claim_due_jobs(clock.now(),timedelta(seconds=10))==[]


def test_verification_encoding_failure_rolls_back_proof_and_pass(client,clock,monkeypatch):
    token,res=reserve(client);clock.moment=PLAN
    from app.modules.verification.service import verify as verify_service
    from app.modules.identity.schemas import SessionContext
    context=SessionContext.model_validate(client.get(f'{API}/me',headers=auth(token)).json())
    def fail(*args,**kwargs):raise RuntimeError('synthetic encoder failure')
    monkeypatch.setattr('qrcode.make',fail)
    with Session(get_engine()) as db:
        with pytest.raises(RuntimeError,match='synthetic encoder'):
            verify_service(db,clock,context,res['id'],res['version'],True,True)
        db.rollback()
    with Session(get_engine()) as db:
        assert list(db.scalars(select(PassCode)))==[]
        assert list(db.scalars(select(VerificationSession)))==[]


def test_consumed_verification_proof_cannot_sign_another_code(client,clock):
    _,res,response=verify(client,clock);assert response.status_code==201
    from app.modules.access.service import issue_pass
    from app.core.errors import ApiError
    grant={'student_id':'stu_synth_0001','building_id':'bldg_a1','verification_id':response.json()['verification_id'],'verified_at':PLAN.isoformat(),'planned_return_at':PLAN.isoformat(),'window_start':(PLAN-timedelta(minutes=30)).isoformat(),'window_end':(PLAN+timedelta(minutes=30)).isoformat()}
    with pytest.raises(ApiError) as error:issue_pass(res['id'],res['version'],grant)
    assert error.value.code=='VERIFICATION_ALREADY_USED'


def test_delayed_summary_uses_revision_at_midnight(client,clock):
    token,res=reserve(client)
    clock.moment=datetime(2026,11,16,0,5,tzinfo=TZ)
    response=client.patch(f"{API}/reservations/{res['id']}",headers=auth(token),json={'expected_version':1,'planned_return_at':(PLAN+timedelta(hours=1)).isoformat()})
    assert response.status_code==200,response.text
    from app.modules.reservation.service import list_for_building_at
    snapshot=list_for_building_at('bldg_a1',NIGHT,datetime(2026,11,16,0,tzinfo=TZ))
    assert len(snapshot)==1 and snapshot[0]['version']==1
    assert datetime.fromisoformat(snapshot[0]['planned_return_at'])==PLAN


def test_correction_appends_and_student_cannot_modify_original(client,clock):
    student,_,response=verify(client,clock)
    scanned=scan(client,clock,response.json()['pass']['token']);assert scanned.status_code==200
    rid=scanned.json()['return_id'];path=f'{API}/return-records/{rid}/corrections'
    assert client.post(path,headers=auth(student),json={'note':'学生无更正权'}).status_code==403
    dorm=token_for(client,'dorm')
    corrected=PLAN-timedelta(minutes=1)
    result=client.post(path,headers=auth(dorm),json={'note':'合成时刻核实','occurred_at':corrected.isoformat()})
    assert result.status_code==201,result.text
    with get_engine().connect() as conn:
        assert conn.execute(text('SELECT occurred_at FROM return_records WHERE return_id=:id'),{'id':rid}).scalar()==PLAN
    history=client.get(path,headers=auth(student)).json()['items']
    assert len(history)==1 and datetime.fromisoformat(history[0]['occurred_at'])==corrected


def test_legacy_cross_college_relationship_cannot_be_overwritten_by_dean(client,clock):
    dean=token_for(client,'college_admin')
    # 旧迁移的 scope 为空，但目录里仍有跨学院负责关系，不能只相信 JSON。
    with Session(get_engine()) as db:
        row=db.scalar(select(RoleAssignment).where(RoleAssignment.user_id=='usr_synth_0002',RoleAssignment.role=='COUNSELOR'))
        row.scope={};db.commit();grant_id=row.id
    response=client.post(f'{API}/management/grants',headers=auth(dean),json={'user_id':'usr_synth_0002','role':'COUNSELOR','student_ids':['stu_synth_0001']})
    assert response.status_code==403
    assert client.delete(f'{API}/management/grants/{grant_id}',headers=auth(dean)).status_code==403
    assert len(directory.get_assigned_students('usr_synth_0002',clock.now()))==6
    visible=client.get(f'{API}/management/grants',headers=auth(dean)).json()['items']
    assert len(next(g for g in visible if g['id']==grant_id)['student_ids'])==6


def test_queued_report_is_suppressed_after_unsubscribe(client,clock):
    from app.worker.scheduler import enqueue
    teacher=token_for(client,'counselor')
    client.put(f'{API}/reports/subscriptions',headers=auth(teacher),json={'daily':True,'weekly':True})
    with get_engine().begin() as conn:
        enqueue(conn,'COUNSELOR_DAILY_REPORT','synthetic:unsubscribe',{'template':'DAILY_REPORT','service_date':str(NIGHT),'recipient_user_ids':['usr_synth_0002']},clock.now())
    response=client.put(f'{API}/reports/subscriptions',headers=auth(teacher),json={'daily':False,'weekly':True})
    assert response.status_code==200
    run_once(clock,timedelta(seconds=60))
    assert client.get(f'{API}/notifications',headers=auth(teacher)).json()['items']==[]
    assert client.get(f'{API}/reports/subscriptions',headers=auth(teacher)).json()=={'daily':False,'weekly':True}


def test_concurrent_policy_publications_keep_one_active_immutable_version(client,clock):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.modules.risk.policy import save
    barrier=Barrier(2)
    def publish(version):
        with Session(get_engine()) as db:
            barrier.wait(timeout=10)
            return save(db,'usr_synth_0004',{'version':version,'window_nights':7,'times_threshold':3,'consecutive_threshold':3},clock.now())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(publish,['synthetic_policy_1','synthetic_policy_2']))
    assert len(results)==2
    with get_engine().connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM policy_versions WHERE active')).scalar()==1
        assert conn.execute(text('SELECT count(*) FROM policy_versions')).scalar()==2
    campus=token_for(client,'campus')
    duplicate=client.put(f'{API}/risk-policy',headers=auth(campus),json=results[0])
    assert duplicate.status_code==409
    assert client.put(f'{API}/risk-policy',headers=auth(token_for(client,'counselor')),json=results[0]).status_code==403


def test_repeated_worker_crashes_stop_at_configured_attempt_limit(client,clock):
    from app.worker.scheduler import enqueue
    from app.core.config import get_settings
    with get_engine().begin() as conn:
        enqueue(conn,'TEST_SYNTH','synthetic:crash_limit',{},clock.now())
        conn.execute(text("UPDATE background_jobs SET status='RUNNING',attempts=:n,lease_until=:at WHERE business_key='synthetic:crash_limit'"),{'n':get_settings().worker_max_attempts,'at':clock.now()-timedelta(seconds=1)})
    assert claim_due_jobs(clock.now(),timedelta(seconds=60))==[]
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT status FROM background_jobs WHERE business_key='synthetic:crash_limit'")).scalar()=='FAILED'


def test_export_idempotency_collision_does_not_expose_another_owners_resource(client,clock):
    from app.modules.exports.service import create
    from app.modules.identity.schemas import SessionContext
    from app.core.errors import ApiError
    campus=token_for(client,'campus')
    context=SessionContext.model_validate(client.get(f'{API}/me',headers=auth(campus)).json())
    payload={'report':'STATISTICS','params':{'date_from':'2026-11-01','date_to':'2026-11-14','group_by':'park'},'idempotency_key':'synthetic:owner_collision'}
    first=create(context,payload,clock.now())
    assert first['requested_by']==context.user_id
    with pytest.raises(ApiError) as error:
        create(context.model_copy(update={'user_id':'usr_synth_0006'}),payload,clock.now())
    assert error.value.code=='EXPORT_NOT_FOUND'


def test_missing_risk_recipients_is_audited_without_fallback_to_campus(client,clock,monkeypatch):
    from app.modules.returns.service import confirm_return
    for day in (12,13,14):
        with get_engine().begin() as conn:
            confirm_return(conn,'stu_synth_0001',date(2026,11,day),'MANUAL',{},datetime(2026,11,day+1,0,40,tzinfo=TZ),f'missing_recipients:{day}')
    monkeypatch.setattr(directory,'get_counselors',lambda *a:[])
    monkeypatch.setattr(directory,'get_duty_staff',lambda *a:[])
    with Session(get_engine()) as db:
        assert events.evaluate_all(db,clock,date(2026,11,14))==1
        row=db.scalars(select(RiskEvent)).one()
        assert row.recipients==[]
        assert db.scalar(select(AuditLog).where(AuditLog.action=='RISK_RECIPIENT_MISSING')) is not None
        assert list(db.scalars(select(BackgroundJob)))==[]


@pytest.mark.parametrize("role", ["COUNSELOR", "IDEOLOGY", "CAMPUS"])
def test_school_cannot_manage_college_teacher_roles(client, clock, role):
    root = auth(token_for(client, "auth_admin"))
    response = client.post(f"{API}/management/grants", headers=root, json={
        "user_id": "usr_synth_0006", "role": role, "student_ids": []})
    assert response.status_code == 403
    with get_engine().connect() as conn:
        grant_id = conn.execute(text("SELECT id FROM role_assignments WHERE role=:role AND active LIMIT 1"), {"role": role}).scalar_one()
    response = client.delete(f"{API}/management/grants/{grant_id}", headers=root)
    assert response.status_code == 403
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT active FROM role_assignments WHERE id=:id"), {"id": grant_id}).scalar_one() is True


def test_school_lists_only_deans_and_can_choose_any_school_teacher(client, clock):
    root = auth(token_for(client, "auth_admin"))
    teachers = client.get(f"{API}/management/users?identity_type=TEACHER", headers=root).json()["items"]
    with get_engine().connect() as conn:
        expected = set(conn.execute(text("SELECT user_id FROM users WHERE identity_types ? 'TEACHER' AND status='ACTIVE'")).scalars())
    assert {u["user_id"] for u in teachers} == expected
    colleges = sorted(directory.all_college_ids())
    target = next(u for u in teachers if u["college_org_id"] != colleges[-1])
    payload = {"user_id": target["user_id"], "role": "COLLEGE_ADMIN", "college_org_ids": [colleges[-1]]}
    response = client.post(f"{API}/management/grants", headers=root, json={**payload, "student_ids": ["stu_synth_0001"]})
    assert response.status_code == 403
    response = client.post(f"{API}/management/grants", headers=root, json=payload)
    assert response.status_code == 201, response.text
    root = auth(token_for(client, "auth_admin"))
    grants = client.get(f"{API}/management/grants", headers=root).json()["items"]
    assert grants and {g["role"] for g in grants} == {"COLLEGE_ADMIN"}
    assert client.delete(f"{API}/management/grants/{response.json()['id']}", headers=root).status_code == 200


def test_school_can_read_all_school_reports_but_has_no_business_write_permissions(client, clock):
    root = auth(token_for(client, "auth_admin"))
    me = client.get(f"{API}/me", headers=root).json()
    with get_engine().connect() as conn:
        expected = set(conn.execute(text("SELECT student_id FROM students")).scalars())
    assert set(me["scope"]["student_ids"]) == expected
    for path in ("/reports/daily", "/reports/weekly"):
        response = client.get(f"{API}{path}", headers=root)
        assert response.status_code == 200, response.text
        assert response.json()["scope_note"] == "统计全校授权范围内的学生。"
    for path in ("/reports/subscriptions", "/risk-events", "/staff-accounts"):
        assert client.get(f"{API}{path}", headers=root).status_code == 403
    assert client.post(f"{API}/reservations", headers=root, json={"planned_return_at": PLAN.isoformat(), "reason": "合成测试"}).status_code == 403
