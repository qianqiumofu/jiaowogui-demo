"""辅导员/思政/学院负责人按范围查询晚归统计：只见负责学生，越权不可见，筛选目录收窄，范围缺失即拒绝。

复用 test_school_statistics 的合成正式返宿与预约场景（clean_db）：students[0]、students[1]
各有 2026-11-17、2026-11-18 两夜正式晚归；students[0] 今日有未撤销预约。范围用 monkeypatch
注入 student_ids，与仓库既有 test_statistics_read_respects_session_scope 同一手法。
"""
import pytest
from sqlalchemy import text

from app.core.db import get_engine
from tests.conftest import API, auth, token_for
from tests.test_school_statistics import data  # noqa: F401  复用合成场景 fixture

pytestmark = pytest.mark.usefixtures('clean_db')

RANGE = {'date_from': '2026-11-17', 'date_to': '2026-11-18'}


def _limit(monkeypatch, role_value, student_ids):
    """在原范围上改写 student_ids：None 表示删除范围键，模拟负责关系未解析。

    保留其余键（如学院负责人的 college_org_ids），因为 authorize 先行守卫会因缺键直接 403，
    统计口径本身只按 student_ids 裁剪。
    """
    from app.modules.identity import service
    original = service.resolve_scope

    def limited(person, role, at):
        scope = dict(original(person, role, at))
        if role.value == role_value:
            if student_ids is None:
                scope.pop('student_ids', None)
                scope.pop('college_org_ids', None)
            else:
                scope['student_ids'] = list(student_ids)
                if role_value == 'COLLEGE_ADMIN' and not scope.get('college_org_ids'):
                    scope['college_org_ids'] = ['org_synth_college']
        return scope

    monkeypatch.setattr(service, 'resolve_scope', limited)


def _totals(client, headers, **params):
    response = client.get(f'{API}/statistics', headers=headers, params={**RANGE, 'group_by': 'none', **params})
    assert response.status_code == 200, response.text
    return response.json()['totals']


def test_campus_sees_whole_school_while_counselor_sees_only_assigned(client, data, monkeypatch):
    _, students, _ = data
    campus = auth(token_for(client, 'campus'))
    whole = _totals(client, campus)
    assert (whole['people'], whole['nights'], whole['returns']) == (2, 4, 4)

    _limit(monkeypatch, 'COUNSELOR', [students[0]])
    counselor = auth(token_for(client, 'counselor'))
    scoped = _totals(client, counselor)
    # 越权隔离：只见本人负责的一名学生，另一名单学生的两夜晚归不计入。
    assert (scoped['people'], scoped['nights'], scoped['returns']) == (1, 2, 2)


def test_scoped_quick_counts_follow_range(client, data, monkeypatch):
    _, students, _ = data
    _limit(monkeypatch, 'COUNSELOR', [students[0]])
    counselor = auth(token_for(client, 'counselor'))
    body = client.get(f'{API}/statistics/quick', headers=counselor, params={'period': 'DAY'}).json()
    assert body['yesterday_returned_people'] == 1
    assert body['today_reserved_people'] == 1


@pytest.mark.parametrize('login,role', [('counselor', 'COUNSELOR'), ('ideology', 'IDEOLOGY'), ('college_admin', 'COLLEGE_ADMIN')])
def test_scoped_roles_all_narrow_to_their_students(client, data, monkeypatch, login, role):
    _, students, _ = data
    _limit(monkeypatch, role, [students[1]])
    headers = auth(token_for(client, login))
    totals = _totals(client, headers)
    assert (totals['people'], totals['nights']) == (1, 2)
    quick = client.get(f'{API}/statistics/quick', headers=headers, params={'period': 'DAY'}).json()
    # students[1] 今日预约已撤销，昨夜有正式晚归。
    assert quick['yesterday_returned_people'] == 1
    assert quick['today_reserved_people'] == 0


def test_scoped_filters_catalog_only_lists_own_directory(client, data, monkeypatch):
    _, students, _ = data
    with get_engine().connect() as conn:
        own_college = conn.execute(text('SELECT college_org_id FROM students WHERE student_id=:id'),
                                   {'id': students[0]}).scalar_one()
    _limit(monkeypatch, 'COUNSELOR', [students[0]])
    headers = auth(token_for(client, 'counselor'))
    catalog = client.get(f'{API}/statistics/filters', headers=headers).json()
    assert catalog['colleges']
    assert {c['org_id'] for c in catalog['colleges']} == {own_college}
    # 片区楼栋数按收窄后的楼栋重算，不显示范围外的栋数。
    for park in catalog['parks']:
        assert park['building_count'] == sum(1 for b in catalog['buildings'] if b['park_org_id'] == park['org_id'])


@pytest.mark.parametrize('role,ids', [('COUNSELOR', []), ('COUNSELOR', None), ('COLLEGE_ADMIN', None)])
def test_unresolved_or_empty_scope_is_rejected_not_whole_school(client, data, monkeypatch, role, ids):
    """负责学生为空或范围未解析一律 403，绝不回退成全校口径。"""
    _limit(monkeypatch, role, ids)
    login = {'COUNSELOR': 'counselor', 'COLLEGE_ADMIN': 'college_admin'}[role]
    headers = auth(token_for(client, login))
    for path, params in (('/statistics', RANGE), ('/statistics/quick', {'period': 'DAY'}), ('/statistics/filters', {})):
        response = client.get(f'{API}{path}', headers=headers, params=params)
        assert response.status_code == 403, (path, response.text)
        assert response.json()['code'] == 'SCOPE_UNRESOLVED'
