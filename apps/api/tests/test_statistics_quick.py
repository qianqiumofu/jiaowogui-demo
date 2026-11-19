"""园区快捷统计沿用真实 PG 合成正式记录；辅导员/思政/学院负责人范围内可见，其裁剪与越权另见范围用例。"""
import pytest
from tests.conftest import API, auth, token_for
from tests.test_school_statistics import data  # 复用合成正式返宿与预约场景

pytestmark = pytest.mark.usefixtures('clean_db')


@pytest.mark.parametrize('period,start,people,nights', [
    ('DAY', '2026-11-18', 2, 2), ('WEEK', '2026-11-16', 2, 4), ('MONTH', '2026-11-01', 2, 4)])
def test_campus_quick_counts_and_server_ranges(client, data, period, start, people, nights):
    headers = auth(token_for(client, 'campus'))
    response = client.get(f'{API}/statistics/quick', headers=headers, params={'period':period})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['date_from'], body['date_to']) == (start, '2026-11-18')
    assert (body['returned_people'], body['returned_nights']) == (people, nights)
    if period == 'DAY':
        assert body['yesterday_returned_people'] == 2
        assert body['today_reserved_people'] == 1
    assert 'items' not in body


@pytest.mark.parametrize('login', ['student', 'auth_admin', 'dorm'])
def test_roles_without_grant_cannot_query_quick_statistics(client, data, login):
    response = client.get(f'{API}/statistics/quick', headers=auth(token_for(client, login)))
    assert response.status_code == 403


def test_level_filters_both_yesterday_and_today_reservations(client, data):
    headers = auth(token_for(client,'campus'))
    # data 首位学生为本科、次位硕士；今日只有首位的未撤销预约。
    bachelor = client.get(f'{API}/statistics/quick',headers=headers,params={'education_level':'BACHELOR'}).json()
    master = client.get(f'{API}/statistics/quick',headers=headers,params={'education_level':'MASTER'}).json()
    assert bachelor['yesterday_returned_people'] == master['yesterday_returned_people'] == 1
    assert bachelor['today_reserved_people'] == 1
    assert master['today_reserved_people'] == 0
