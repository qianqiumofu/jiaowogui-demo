from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from app.core.clock import build_clock
from app.core.db import get_engine
from app.modules.exports import service
from tests.conftest import API, auth, token_for
from tests.test_exports import _create, _campus, _purge, _run_export_handler

pytestmark = pytest.mark.usefixtures('seeded_demo_db')


@pytest.mark.parametrize('generated', [False, True])
def test_delete_hides_export_clears_file_and_keeps_audit(client, generated):
    job = _create(client, idempotency_key='delete-synth')
    export_id = job['export_id']
    headers = _campus(client)
    try:
        if generated:
            _run_export_handler(export_id)
        for _ in range(2):
            response = client.delete(f'{API}/exports/{export_id}', headers=headers)
            assert response.status_code == 200, response.text
            assert response.json() == {'export_id': export_id, 'deleted': True}
        listed = client.get(f'{API}/exports', headers=headers).json()['items']
        assert export_id not in {j['export_id'] for j in listed}
        for suffix in ['', '/download']:
            assert client.get(f'{API}/exports/{export_id}{suffix}', headers=headers).status_code == 404
        _run_export_handler(export_id)
        with get_engine().connect() as conn:
            row = conn.execute(text('SELECT * FROM export_jobs WHERE export_id=:id'), {'id': export_id}).mappings().one()
            assert row['deleted_at'] is not None
            assert row['csv_content'] is None and row['file_name'] is None
            assert row['requested_by'] == job['requested_by'] and row['params'] == job['params']
        replay = client.post(f'{API}/exports', headers=headers, json={'report':'STATISTICS','params':job['params'],'idempotency_key':'delete-synth'})
        assert replay.status_code == 404
    finally:
        _purge(export_id)


def test_cannot_delete_another_users_export(client):
    job = _create(client)
    try:
        counselor = auth(token_for(client, 'counselor'))
        denied = client.delete(f"{API}/exports/{job['export_id']}", headers=counselor)
        assert denied.status_code == 404
        assert client.get(f"{API}/exports/{job['export_id']}", headers=_campus(client)).status_code == 200
    finally:
        _purge(job['export_id'])


@pytest.mark.parametrize('login', ['student', 'dorm'])
def test_delete_requires_action_permission(client, login):
    response = client.delete(f'{API}/exports/exp_synth_unknown', headers=auth(token_for(client, login)))
    assert response.status_code == 403
    assert response.json()['code'] == 'FORBIDDEN_ACTION'


@pytest.mark.parametrize('login', ['counselor', 'ideology', 'college_admin'])
def test_scoped_roles_can_delete_only_their_own_export(client, login):
    headers = auth(token_for(client, login))
    response = client.post(f'{API}/exports', headers=headers, json={'report':'STATISTICS','params':{'date_from':'2026-11-01','date_to':'2026-11-14'}})
    assert response.status_code == 201, response.text
    export_id = response.json()['export_id']
    try:
        assert client.delete(f'{API}/exports/{export_id}', headers=headers).status_code == 200
    finally:
        _purge(export_id)


def test_delete_waits_for_inflight_build_then_removes_generated_file(client, monkeypatch):
    job = _create(client)
    export_id = job['export_id']
    headers = _campus(client)
    entered, release, delete_started = Event(), Event(), Event()
    original = service.render_csv

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    def remove():
        delete_started.set()
        return client.delete(f'{API}/exports/{export_id}', headers=headers)

    monkeypatch.setattr(service, 'render_csv', paused)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            build = pool.submit(service.build, export_id, build_clock().now())
            try:
                assert entered.wait(10)
                deleted = pool.submit(remove)
                assert delete_started.wait(10)
            finally:
                release.set()
            build.result(timeout=15)
            assert deleted.result(timeout=15).status_code == 200
        with get_engine().connect() as conn:
            row = conn.execute(text('SELECT csv_content,deleted_at FROM export_jobs WHERE export_id=:id'), {'id': export_id}).one()
            assert row.csv_content is None and row.deleted_at is not None
    finally:
        release.set()
        _purge(export_id)
