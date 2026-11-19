"""千人场景必须在真实 PostgreSQL 上验收，结束后恢复固定种子。"""
from datetime import date

import pytest
from sqlalchemy import text

from app.core.db import get_engine
from app.db.experience import populate
from app.db.seed import reset, seed
from tests.conftest import API, auth, token_for


def test_thousand_student_experience(postgres_schema, client):
    engine = get_engine()
    reset(engine)
    try:
        result = populate(engine, date(2026, 11, 15))
        assert result == {"students":1000,"colleges":5,"buildings":10,"classes":40}
        with engine.connect() as conn:
            scalar = lambda sql: conn.execute(text(sql)).scalar()
            assert scalar("SELECT count(*) FROM students") == 1000
            assert scalar("SELECT count(DISTINCT school_id) FROM students") == 1000
            assert scalar("SELECT count(DISTINCT user_id) FROM students") == 1000
            assert scalar("SELECT count(*) FROM (SELECT college_org_id,class_name FROM students GROUP BY 1,2 HAVING count(*)=25) x") == 40
            assert scalar("SELECT count(*) FROM students s WHERE NOT EXISTS(SELECT 1 FROM counselor_assignments a WHERE a.student_id=s.student_id)") == 0
            assert scalar("SELECT count(*) FROM (SELECT r.building_id FROM residences r JOIN students s USING(student_id) GROUP BY 1 HAVING count(DISTINCT s.gender)>1) x") == 0
            assert scalar("SELECT count(*) FROM (SELECT building_id,room_no FROM residences GROUP BY 1,2 HAVING count(*)>4) x") == 0
            assert scalar("SELECT count(*) FROM role_assignments WHERE role='COLLEGE_ADMIN' AND active") == 5
            assert scalar("SELECT count(*) FROM role_assignments WHERE role='COUNSELOR' AND active") == 20
            assert scalar("SELECT count(*) FROM users WHERE source='STAFF_LOCAL'") == 20
            assert scalar("SELECT count(DISTINCT building_id) FROM duty_assignments") == 10
            assert scalar("SELECT count(*) FROM (SELECT student_id,service_date FROM return_records GROUP BY 1,2 HAVING count(*)>1) x") == 0
            assert scalar("SELECT count(*) FROM return_records") > 500
            assert scalar("SELECT count(*) FROM return_records WHERE source='QR' AND pass_id IS NOT NULL") > 0
            assert scalar("SELECT count(*) FROM passage_attempts WHERE status='UNKNOWN'") > 0
            assert scalar("SELECT count(*) FROM passage_attempts WHERE status='FAILED'") > 0
            assert scalar("SELECT count(DISTINCT status) FROM risk_events") == 3
            assert scalar("SELECT count(*) FROM risk_events WHERE recipients ? 'usr_synth_0004'") == 0
            assert scalar("SELECT count(*) FROM reservation_revisions WHERE source='RESCHEDULE'") > 0
            assert scalar("SELECT count(*) FROM reservations WHERE status='CANCELLED'") > 0
            assert scalar("SELECT count(*) FROM reservations WHERE status='CLOSED'") > 0
            assert scalar("SELECT count(*) FROM background_jobs WHERE job_type ILIKE '%OVERDUE%' OR job_type ILIKE '%UNCONFIRMED%'") == 0
        math_admin = auth(token_for(client, "college_admin_2"))
        teachers = client.get(f"{API}/management/users?identity_type=TEACHER", headers=math_admin)
        assert teachers.status_code == 200
        assert len(teachers.json()["items"]) == 6
        assert {u["college_org_id"] for u in teachers.json()["items"]} == {"org_college_math"}
        assert client.get(f"{API}/management/users?identity_type=UNKNOWN", headers=math_admin).status_code == 422
        students = client.get(f"{API}/directory/students", headers=math_admin).json()["items"]
        assert len(students) == 200
        assert {s["college_org_id"] for s in students} == {"org_college_math"}
        response = client.post(f"{API}/management/grants", headers=math_admin, json={
            "user_id":"usr_exp_c1_0","role":"COUNSELOR","student_ids":["stu_synth_0001"]})
        assert response.status_code == 403
        counselor = auth(token_for(client, "counselor_2_1"))
        assert len(client.get(f"{API}/directory/students", headers=counselor).json()["items"]) == 50
        assert client.get(f"{API}/statistics", headers=counselor).status_code == 403
        assert client.get(f"{API}/management/grants", headers=counselor).status_code == 403
    finally:
        reset(engine)
        seed(engine, date(2026, 11, 15), "Asia/Shanghai")
