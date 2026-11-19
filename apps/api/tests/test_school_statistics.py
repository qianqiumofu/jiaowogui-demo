"""校级日周月统计：真实 PG、正式事实、主动名单查询与范围约束。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.clock import Clock
from app.core.db import get_engine
from app.modules.returns import service as returns
from tests.conftest import API, auth, token_for

TZ = ZoneInfo('Asia/Shanghai')
TODAY = date(2026, 11, 19)
YESTERDAY = TODAY - timedelta(days=1)
pytestmark = pytest.mark.usefixtures('clean_db')


class FixedClock(Clock):
    def __init__(self, moment):
        super().__init__('Asia/Shanghai')
        self.moment = moment

    def now(self):
        return self.moment


@pytest.fixture()
def data(client):
    clock = FixedClock(datetime(2026, 11, 19, 12, tzinfo=TZ))
    client.app.state.clock = clock
    client.app.state.session_store._clock = clock
    with get_engine().begin() as conn:
        students = list(conn.execute(text('SELECT student_id FROM students ORDER BY student_id LIMIT 3')).scalars())
        for sid in students[:2]:
            for night in (YESTERDAY, YESTERDAY - timedelta(days=1)):
                returns.confirm_return(conn, sid, night, 'MANUAL', {'building_id': 'bldg_a1'},
                    datetime.combine(night + timedelta(days=1), datetime.min.time(), TZ) + timedelta(minutes=40),
                    f'school-stat-{sid}-{night}')
        # FULFILLED 没有正式记录也不计晚归；取消预约不计今日预约。
        for index, (sid, night, status) in enumerate([
            (students[2], YESTERDAY, 'FULFILLED'),
            (students[0], TODAY, 'ACTIVE'), (students[1], TODAY, 'CANCELLED')]):
            conn.execute(text("""INSERT INTO reservations
                (id,student_id,school_id,service_date,planned_return_at,reason,status,version,created_at,updated_at)
                VALUES (:id,:sid,:school_id,:night,:plan,'合成统计测试',:status,1,:now,:now)"""),
                {'id': f'res_school_stat_{index}', 'sid': sid, 'night': night, 'status': status,
                 'plan': datetime.combine(night + timedelta(days=1), datetime.min.time(), TZ) + timedelta(minutes=40),
                 'school_id': conn.execute(text('SELECT school_id FROM students WHERE student_id=:id'), {'id':sid}).scalar_one(),
                 'now': clock.now()})
    return auth(token_for(client, 'auth_admin')), students, clock


def get(client, headers, path='/reports/overview', **params):
    response = client.get(f'{API}{path}', headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_has_counts_only_and_separates_actual_from_reserved(client, data):
    headers, _, _ = data
    body = get(client, headers)
    assert body['yesterday_returned_people'] == 2
    assert body['today_reserved_people'] == 1
    assert body['returned_nights'] == 2
    assert not {'items', 'students', 'display_name', 'school_id'}.intersection(body)
    assert body['date_from'] == body['date_to'] == YESTERDAY.isoformat()
    today = get(client, headers, '/reports/overview/students', dataset='RESERVED')
    assert today['total_matches'] == 1
    assert today['items'][0]['return_nights'] == 0


@pytest.mark.parametrize('period,start', [('WEEK', '2026-11-16'), ('MONTH', '2026-11-01')])
def test_repeated_students_require_multiple_formal_nights(client, data, period, start):
    headers, students, _ = data
    body = get(client, headers, period=period)
    assert (body['date_from'], body['date_to']) == (start, '2026-11-18')
    assert (body['returned_people'], body['returned_nights'], body['repeated_people']) == (2, 4, 2)
    rows = get(client, headers, '/reports/overview/students', period=period, dataset='REPEATED')
    assert {r['student_id'] for r in rows['items']} == set(students[:2])
    assert all(r['return_nights'] == 2 for r in rows['items'])


def test_filters_apply_before_aggregation_and_cursor_cannot_cross_filters(client, data):
    headers, _, _ = data
    first = get(client, headers, '/reports/overview/students', period='WEEK', dataset='REPEATED', limit=1)
    assert len(first['items']) == 1 and first['next_cursor']
    second = get(client, headers, '/reports/overview/students', period='WEEK', dataset='REPEATED', limit=1, cursor=first['next_cursor'])
    assert second['items'][0]['student_id'] != first['items'][0]['student_id']
    assert second['next_cursor'] is None
    row = first['items'][0]
    filters = {key: row[key] for key in ('college_org_id', 'grade', 'park_org_id', 'building_id') if row[key]}
    body = get(client, headers, '/reports/overview/students', period='WEEK', dataset='REPEATED', **filters)
    assert row['student_id'] in {r['student_id'] for r in body['items']}
    for key, value in filters.items():
        assert all(r[key] == value for r in body['items'])
    response = client.get(f'{API}/reports/overview/students', headers=headers,
        params={'period':'MONTH', 'dataset':'REPEATED', 'cursor':first['next_cursor']})
    assert response.status_code == 422
    response = client.get(f'{API}/reports/overview/students', headers=headers,
        params={'dataset':'RETURNED', 'building_id':'unknown'})
    assert response.status_code == 422


@pytest.mark.parametrize('moment,current,end', [
    ('2026-12-01T05:59:59+08:00', '2026-11-30', '2026-11-29'),
    ('2026-12-01T06:00:00+08:00', '2026-12-01', '2026-11-30'),
    ('2027-01-01T06:00:00+08:00', '2027-01-01', '2026-12-31'),
])
def test_business_day_month_and_year_boundaries(client, data, moment, current, end):
    headers, _, clock = data
    clock.moment = datetime.fromisoformat(moment)
    headers = auth(token_for(client, 'auth_admin'))
    body = get(client, headers, period='MONTH')
    assert body['current_service_date'] == current
    assert body['date_to'] == end
    assert body['date_from'] == end[:8] + '01'


def test_statistics_read_respects_session_scope(client, data, monkeypatch):
    headers, students, _ = data
    from app.modules.identity import service
    original = service.resolve_scope
    def limited(person, role, at):
        scope = original(person, role, at)
        if role.value == 'AUTH_ADMIN':
            scope['student_ids'] = [students[0]]
        return scope
    monkeypatch.setattr(service, 'resolve_scope', limited)
    assert get(client, headers)['returned_people'] == 1
    rows = get(client, headers, '/reports/overview/students', period='WEEK', dataset='REPEATED')
    assert {r['student_id'] for r in rows['items']} == {students[0]}


@pytest.mark.parametrize('login', ['student', 'teacher', 'college_admin', 'counselor', 'ideology', 'dorm', 'campus'])
def test_other_roles_cannot_use_school_statistics(client, data, login):
    headers = auth(token_for(client, login))
    for path in ('/reports/overview', '/reports/overview/options', '/reports/overview/students?dataset=RETURNED'):
        assert client.get(f'{API}{path}', headers=headers).status_code == 403
