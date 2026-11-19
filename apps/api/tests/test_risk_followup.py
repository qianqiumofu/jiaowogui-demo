"""真实 PG：通知不等于人工接手，跟进追加留痕且重放不重复。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.db import get_engine
from app.db.models import RiskEvent, RiskAction, Notification
from app.modules.risk import events
from app.modules.returns.service import confirm_return
from app.worker.main import run_once
from tests.conftest import API, auth, token_for

pytestmark = pytest.mark.usefixtures('clean_db')
TZ = ZoneInfo('Asia/Shanghai')


class RiskClock(Clock):
    def now(self):
        return datetime(2026, 11, 15, 10, tzinfo=TZ)


@pytest.fixture()
def event(client):
    clock = RiskClock('Asia/Shanghai')
    client.app.state.clock = clock
    client.app.state.session_store._clock = clock
    for day in (12, 13, 14):
        with get_engine().begin() as conn:
            confirm_return(conn, 'stu_synth_0001', date(2026, 11, day), 'MANUAL', {},
                           datetime(2026, 11, day + 1, 0, 40, tzinfo=TZ), f'followup:{day}')
    with Session(get_engine()) as db:
        events.evaluate_all(db, clock, date(2026, 11, 14))
        event_id = db.scalars(select(RiskEvent.id)).one()
    return event_id, clock


def post(client, headers, event_id, action, note='合成跟进说明', key='followup-synth-1'):
    body = {'note':note}
    if action == 'follow-up':
        body['idempotency_key'] = key
    return client.post(f'{API}/risk-events/{event_id}/{action}', headers=headers, json=body)


def test_delivered_notification_is_not_a_manual_followup(client, event):
    event_id, clock = event
    run_once(clock, timedelta(seconds=60))
    with Session(get_engine()) as db:
        assert list(db.scalars(select(Notification).where(Notification.template == 'RISK_ALERT')))
        assert db.get(RiskEvent, event_id).status == 'OPEN'
        assert list(db.scalars(select(RiskAction))) == []


def test_complete_followup_workflow_and_replay(client, event):
    event_id, _ = event
    headers = auth(token_for(client, 'counselor'))
    assert post(client, headers, event_id, 'follow-up').status_code == 409
    assert post(client, headers, event_id, 'resolve').status_code == 409
    assert post(client, headers, event_id, 'ack').json()['status'] == 'ACKNOWLEDGED'
    for _ in range(2):
        response = post(client, headers, event_id, 'follow-up')
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'ACKNOWLEDGED'
    assert post(client, headers, event_id, 'follow-up', note='不同内容').status_code == 409
    assert post(client, headers, event_id, 'follow-up', note='第二次沟通', key='followup-synth-2').status_code == 200
    assert post(client, headers, event_id, 'resolve', note='已核实合成情况并完成跟进').json()['status'] == 'RESOLVED'
    assert post(client, headers, event_id, 'follow-up', key='after-resolve').status_code == 409
    listed = client.get(f'{API}/risk-events', headers=headers).json()['items'][0]
    assert listed['display_name'] and listed['school_id']
    history = listed['actions']
    assert [a['action'] for a in history].count('FOLLOW_UP') == 2
    assert all(a['actor_display_name'] for a in history)


@pytest.mark.parametrize('login', ['campus','college_admin','student','auth_admin','teacher'])
def test_readonly_and_other_roles_cannot_add_followup(client, event, login):
    event_id, _ = event
    headers = auth(token_for(client, login))
    assert post(client, headers, event_id, 'follow-up').status_code == 403


def test_scope_cannot_be_bypassed_and_whitespace_is_not_followup(client, event):
    event_id, _ = event
    headers = auth(token_for(client, 'counselor'))
    assert post(client, headers, event_id, 'ack', note='   ').status_code == 422
    allowed = set(client.get(f'{API}/me', headers=headers).json()['scope']['student_ids'])
    with get_engine().begin() as conn:
        outside = next(sid for sid in conn.execute(text('SELECT student_id FROM students ORDER BY student_id')).scalars() if sid not in allowed)
        conn.execute(text("UPDATE risk_events SET student_id=:student WHERE id=:event"), {'student':outside, 'event':event_id})
    assert post(client, headers, event_id, 'follow-up').status_code == 404
