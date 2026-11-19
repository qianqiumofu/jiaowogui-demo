"""在当前数据模型下补交付包的楼栋晚归单，不导入对方固定值班表。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.clock import Clock
from app.core.db import get_engine
from app.modules.building_list import service
from app.modules.returns import service as returns
from tests.conftest import API, auth, token_for

pytestmark = pytest.mark.usefixtures('clean_db')
TZ = ZoneInfo('Asia/Shanghai')
NIGHT = date(2026, 11, 14)
ANCHOR = datetime(2026, 11, 15, 0, tzinfo=TZ)


@pytest.fixture()
def campus(client):
    class SummaryClock(Clock):
        def now(self): return datetime(2026, 11, 15, 10, tzinfo=TZ)
    clock = SummaryClock('Asia/Shanghai')
    client.app.state.clock = clock
    client.app.state.session_store._clock = clock
    return auth(token_for(client, 'campus'))


def query(client, headers, **params):
    response = client.get(f'{API}/campus/night-summary', headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_pending_is_not_zero_and_defaults_to_latest_due_night(client, campus):
    body = query(client, campus, building_id='bldg_a1')
    assert body['service_date'] == NIGHT.isoformat()
    row = body['items'][0]
    assert row['summary_status'] == 'PENDING' and row['headcount'] is None
    assert row['responsible_source'] == 'LIVE'
    assert row['responsible']


def test_snapshot_freezes_people_and_manual_returns_are_counted(client, campus, monkeypatch):
    service.write_snapshot('bldg_a1', NIGHT, ANCHOR, [])
    original = query(client, campus, building_id='bldg_a1')['items'][0]
    assert original['responsible_source'] == 'SNAPSHOT'
    from app.modules.directory import service as directory
    monkeypatch.setattr(directory, 'get_duty_staff', lambda *args: [])
    with get_engine().begin() as conn:
        returns.confirm_return(conn, 'stu_synth_0001', NIGHT, 'MANUAL', {}, ANCHOR.replace(minute=40), 'summary-return-synth')
    row = query(client, campus, building_id='bldg_a1')['items'][0]
    assert row['responsible'] == original['responsible']
    assert row['returned_count'] == 1
    assert row['headcount'] == 0


def test_old_snapshot_does_not_invent_historical_responsibility(client, campus):
    service.write_snapshot('bldg_a1', NIGHT, ANCHOR, [])
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE building_list_snapshots SET payload=payload-'duty_staff' WHERE building_id='bldg_a1'"))
    row = query(client, campus, building_id='bldg_a1')['items'][0]
    assert row['responsible_source'] == 'UNAVAILABLE' and row['responsible'] == []


@pytest.mark.parametrize('login', ['student','dorm','counselor','college_admin','auth_admin'])
def test_other_roles_cannot_read_campus_summary(client, campus, login):
    assert client.get(f'{API}/campus/night-summary', headers=auth(token_for(client, login))).status_code == 403
