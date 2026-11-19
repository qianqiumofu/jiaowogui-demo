"""用户确认的交付差异：层次、零行、补录时间；全部连接隔离 PostgreSQL。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.clock import Clock
from app.core.db import get_engine
from tests.conftest import API, auth, token_for

pytestmark = pytest.mark.usefixtures('clean_db')


@pytest.fixture()
def day(client):
    class DayClock(Clock):
        def now(self): return datetime(2026, 11, 15, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
    clock = DayClock('Asia/Shanghai')
    client.app.state.clock = clock
    client.app.state.session_store._clock = clock
    return client


def test_education_filter_partitions_facts_roster_and_reservations(day):
    headers = auth(token_for(day, 'campus'))
    query = {'date_from':'2026-11-01', 'date_to':'2026-11-14', 'group_by':'park'}
    total = day.get(f'{API}/statistics', headers=headers, params=query).json()
    parts = []
    for level in ('BACHELOR', 'MASTER', 'DOCTORAL'):
        response = day.get(f'{API}/statistics', headers=headers, params={**query, 'education_level':level})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['filters']['education_level'] == level
        assert body['totals']['enrolled'] > 0
        assert sum(r['enrolled'] for r in body['rows']) == body['totals']['enrolled']
        parts.append(body['totals'])
    for metric in ('returns','enrolled','nights'):
        assert sum(p[metric] for p in parts) == total['totals'][metric]
    for path in ('/statistics', '/statistics/quick'):
        assert day.get(API+path, headers=headers, params={'education_level':'FAKE'}).status_code == 422


def test_quick_cards_match_filtered_formal_statistics(day):
    headers = auth(token_for(day, 'campus'))
    for level in ('BACHELOR', 'MASTER', 'DOCTORAL'):
        quick = day.get(f'{API}/statistics/quick', headers=headers, params={'period':'DAY','education_level':level})
        assert quick.status_code == 200, quick.text
        body = quick.json()
        actual = day.get(f'{API}/statistics', headers=headers, params={'date_from':body['date_from'], 'date_to':body['date_to'], 'education_level':level}).json()
        assert body['yesterday_returned_people'] == actual['totals']['people']


def test_unknown_education_remains_in_all_but_not_any_named_level(day):
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE students SET education_level=NULL WHERE student_id='stu_synth_0001'"))
    headers = auth(token_for(day, 'campus'))
    query = {'date_from':'2030-01-01','date_to':'2030-01-01'}
    all_count = day.get(f'{API}/statistics',headers=headers,params=query).json()['totals']['enrolled']
    counts = [day.get(f'{API}/statistics',headers=headers,params={**query,'education_level':level}).json()['totals']['enrolled'] for level in ('BACHELOR','MASTER','DOCTORAL')]
    assert all_count == sum(counts) + 1


@pytest.mark.parametrize('moment,accepted', [
    ('2026-11-14T23:59:59+08:00',False), ('2026-11-15T00:00:00+08:00',True),
    ('2026-11-15T05:59:59+08:00',True), ('2026-11-15T06:00:00+08:00',False),
    ('2026-11-14T16:00:00+00:00',True), ('2026-11-15T07:00:00+08:00',False),
])
def test_daytime_history_manual_record_checks_actual_time(day, moment, accepted):
    headers = auth(token_for(day, 'dorm'))
    response = day.post(f'{API}/return-records/manual',headers=headers,json={
        'student_id':'stu_synth_0001','building_id':'bldg_a1','occurred_at':moment,
        'idempotency_key':'manual_boundary_synth'})
    assert response.status_code == (200 if accepted else 422), response.text
    if accepted:
        assert response.json()['service_date'] == '2026-11-14'
        assert response.json()['recorded_at'].startswith('2026-11-15T12:00:00')


def test_education_export_accepts_only_valid_filter_at_creation(day):
    headers = auth(token_for(day, 'campus'))
    params = {'date_from':'2026-11-01','date_to':'2026-11-14','education_level':'MASTER'}
    good = day.post(f'{API}/exports',headers=headers,json={'report':'STATISTICS','params':params})
    assert good.status_code in (200,201,202),good.text
    bad = day.post(f'{API}/exports',headers=headers,json={'report':'STATISTICS','params':{**params,'education_level':'FAKE'}})
    assert bad.status_code == 422


def test_filtered_export_content_matches_statistics(day):
    from app.modules.exports import service as exports
    import csv
    import io
    headers = auth(token_for(day, 'campus'))
    params = {'date_from':'2030-01-01','date_to':'2030-01-01','education_level':'MASTER'}
    body = day.get(f'{API}/statistics',headers=headers,params=params).json()
    with get_engine().connect() as conn:
        content, count = exports.render_csv(conn,body)
    assert count == len(body['rows'])
    data = list(csv.reader(io.StringIO(content.lstrip('\ufeff'))))
    assert any('硕士' in cell for row in data for cell in row)
    assert sum(int(row[-1]) for row in data if len(row)==7 and row[0] in {r['label'] for r in body['rows']}) == body['totals']['enrolled']


@pytest.mark.parametrize('login',['student','auth_admin','dorm'])
def test_new_filter_does_not_expand_statistics_permission(day,login):
    """培养层次筛选本身不新授权任何角色。

    辅导员/思政/学院负责人是后续「按范围查晚归」单独授予 statistics:read 的（范围内可见），
    其裁剪与越权见 test_statistics_scoped.py；此处只校验仍无该动作的角色被拒。
    """
    response = day.get(f'{API}/statistics',headers=auth(token_for(day,login)),params={'education_level':'MASTER'})
    assert response.status_code == 403
