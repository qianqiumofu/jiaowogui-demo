import pytest
"""园区受控导出：发起即排队、worker 渲染、只有本人能下载、过期后清空内容。

对应基线 R11「导出与明细另设字段权限」与 R14 统计口径：导出的永远是 `statistics` 的聚合结果，
所以联系方式与学生明细不在字段范围内。渲染走 `app/worker/registry.py` 注册的 EXPORT_BUILD
处理器（调度循环仍只有 A 那一个）。
"""

from datetime import timedelta

from sqlalchemy import text

from app.core.clock import build_clock
from app.core.db import get_engine
from app.worker.registry import HANDLERS
from tests.conftest import API, auth, token_for

PARAMS = {"date_from": "2026-11-01", "date_to": "2026-11-14", "group_by": "park"}
RETENTION_DAYS = 7


pytestmark = pytest.mark.usefixtures("seeded_demo_db")

def _campus(client) -> dict:
    return auth(token_for(client, "campus"))


def _create(client, params=None, **extra) -> dict:
    payload = {"report": "STATISTICS", "params": params or PARAMS, **extra}
    response = client.post(f"{API}/exports", headers=_campus(client), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _run_export_handler(export_id: str) -> None:
    """直接调用注册表里的处理器，等价于 worker 领到这一条任务；不牵动 A 的快照任务。"""
    assert "EXPORT_BUILD" in HANDLERS
    HANDLERS["EXPORT_BUILD"]({"payload": {"export_id": export_id}})


def _export_count() -> int:
    """任务表总行数。库里可能留着演示/手工跑出的历史任务，所以负面用例只比对前后差值。"""
    with get_engine().connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM export_jobs")).scalar())


def _purge(*export_ids: str) -> None:
    ids = list(export_ids)
    with get_engine().begin() as conn:
        for export_id in ids:
            conn.execute(text("DELETE FROM background_jobs WHERE business_key = :k"),
                         {"k": f"EXPORT_BUILD:{export_id}"})
            conn.execute(text("DELETE FROM export_jobs WHERE export_id = :i"), {"i": export_id})


def _job_state(export_id: str) -> dict:
    with get_engine().connect() as conn:
        job = conn.execute(
            text("SELECT status, attempts FROM background_jobs WHERE business_key = :k"),
            {"k": f"EXPORT_BUILD:{export_id}"},
        ).mappings().first()
        row = conn.execute(
            text("SELECT csv_content IS NULL AS cleared, expires_at - done_at AS retention "
                 "FROM export_jobs WHERE export_id = :i"),
            {"i": export_id},
        ).mappings().one()
    return {"job": job, "export": row}


def test_create_only_queues_the_job_and_returns_pending(client) -> None:
    created = _create(client)
    try:
        assert created["status"] == "PENDING"
        assert created["downloadable"] is False
        assert created["file_name"] is None and created["row_count"] is None
        assert created["requested_by"] == "usr_synth_0004"
        assert created["params"] == {**PARAMS, "attribution": "snapshot"}
        state = _job_state(created["export_id"])
        assert state["job"] is not None and state["job"]["status"] == "PENDING"
    finally:
        _purge(created["export_id"])


def test_worker_builds_a_csv_that_matches_the_statistics_read_model(client) -> None:
    created = _create(client)
    export_id = created["export_id"]
    try:
        _run_export_handler(export_id)
        done = client.get(f"{API}/exports/{export_id}", headers=_campus(client)).json()
        assert done["status"] == "DONE" and done["downloadable"] is True
        assert done["file_name"] == "jiaowogui_statistics_20261101-20261114_park.csv"

        download = client.get(f"{API}/exports/{export_id}/download", headers=_campus(client))
        assert download.status_code == 200, download.text
        assert download.headers["content-type"].startswith("text/csv")
        assert 'attachment; filename="jiaowogui_statistics_20261101-20261114_park.csv"' in (
            download.headers["content-disposition"]
        )
        csv_text = download.text
        assert csv_text.startswith("\ufeff")  # BOM：Excel 直接双击不乱码
        # 空行只是版式，剔除后按下标找表头会把版式改动当成回归，所以按内容定位。
        lines = [line for line in csv_text.lstrip("\ufeff").splitlines() if line]
        assert lines[0].startswith("报表")
        assert "业务夜区间,2026-11-01 至 2026-11-14" in csv_text
        table_start = lines.index("片区,晚归人数,晚归夜数,返宿次数,扫码返宿次数,人工补录次数,在册人数")
        assert lines[-1].split(",")[0] == "合计"
        # row_count 只数数据行，合计行是版式追加的。
        assert len(lines) - table_start - 1 == done["row_count"] + 1

        # 同一份口径下，CSV 的合计必须与 /statistics 的总计逐项相等。
        statistics = client.get(f"{API}/statistics", headers=_campus(client), params=PARAMS).json()
        totals = statistics["totals"]
        cells = lines[-1].split(",")[1:]
        assert [int(cell) for cell in cells] == [
            totals[key] for key in
            ("people", "nights", "returns", "qr_returns", "manual_returns", "enrolled")
        ]
        # 保留期是可配置的 Demo 默认，取值写死在测试里锁住。
        assert _job_state(export_id)["export"]["retention"] == timedelta(days=RETENTION_DAYS)
    finally:
        _purge(export_id)


def test_the_export_never_carries_student_rows_or_contacts(client) -> None:
    created = _create(client, params={**PARAMS, "group_by": "building"})
    export_id = created["export_id"]
    try:
        _run_export_handler(export_id)
        csv_text = client.get(f"{API}/exports/{export_id}/download", headers=_campus(client)).text
        assert "stu_synth" not in csv_text and "2023S0001" not in csv_text
        assert "联系" not in csv_text and "手机" not in csv_text
        assert not any(cell.isdigit() and len(cell) >= 7 for line in csv_text.splitlines()
                       for cell in line.split(","))
    finally:
        _purge(export_id)


def test_repeating_the_idempotency_key_returns_the_same_task(client) -> None:
    first = _create(client, idempotency_key="test-dedup")
    try:
        again = client.post(
            f"{API}/exports",
            headers=_campus(client),
            json={"report": "STATISTICS", "params": PARAMS, "idempotency_key": "test-dedup"},
        )
        assert again.status_code == 201, again.text
        assert again.json()["export_id"] == first["export_id"]
        with get_engine().connect() as conn:
            jobs = conn.execute(
                text("SELECT COUNT(*) FROM background_jobs WHERE business_key = :k"),
                {"k": f"EXPORT_BUILD:{first['export_id']}"},
            ).scalar()
        assert jobs == 1
    finally:
        _purge(first["export_id"])


def test_export_rejects_any_caliber_that_statistics_does_not_accept(client) -> None:
    before = _export_count()
    cases = [
        ({"group_by": "park"}, "missing"),
        ({"date_from": "2026-11-01", "date_to": "2026-11-14", "student_id": "stu_synth_0001"}, "unknown"),
        ({"date_from": "2026-11-14", "date_to": "2026-11-01"}, "date_from"),
        ({"date_from": "2026-11-01", "date_to": "2026-11-14", "group_by": "room"}, "allowed"),
    ]
    for params, detail_key in cases:
        response = client.post(
            f"{API}/exports", headers=_campus(client), json={"report": "STATISTICS", "params": params}
        )
        assert response.status_code == 422, (params, response.text)
        body = response.json()
        assert body["code"] == "VALIDATION_FAILED"
        assert detail_key in body["details"], (params, body)
    bad_report = client.post(
        f"{API}/exports",
        headers=_campus(client),
        json={"report": "RAW_ROWS", "params": PARAMS},
    )
    assert bad_report.status_code == 422
    assert bad_report.json()["details"] == {"value": "RAW_ROWS"}
    assert _export_count() == before


def test_expired_content_is_forgotten_but_the_task_stays_auditable(client) -> None:
    created = _create(client)
    export_id = created["export_id"]
    try:
        _run_export_handler(export_id)
        with get_engine().begin() as conn:
            conn.execute(
                text("UPDATE export_jobs SET expires_at = done_at - interval '1 second' "
                     "WHERE export_id = :i"),
                {"i": export_id},
            )
        detail = client.get(f"{API}/exports/{export_id}", headers=_campus(client)).json()
        assert detail["status"] == "DONE"
        assert detail["downloadable"] is False
        assert detail["file_name"] is None
        refused = client.get(f"{API}/exports/{export_id}/download", headers=_campus(client))
        assert refused.status_code == 410, refused.text
        assert refused.json()["code"] == "EXPORT_EXPIRED"
        assert _job_state(export_id)["export"]["cleared"] is True
    finally:
        _purge(export_id)


def test_a_task_requested_by_someone_else_is_not_even_found(client) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("INSERT INTO export_jobs (export_id, report, requested_by, params, status, csv_content, "
                 "file_name, done_at, expires_at) "
                 "VALUES ('exp_test_foreign', 'STATISTICS', 'usr_synth_0001', CAST(:p AS JSONB), 'DONE', "
                 "'x', 'foreign.csv', now(), now() + interval '7 days')"),
            {"p": '{"date_from":"2026-11-01","date_to":"2026-11-14"}'},
        )
    try:
        for path in (f"{API}/exports/exp_test_foreign", f"{API}/exports/exp_test_foreign/download"):
            response = client.get(path, headers=_campus(client))
            assert response.status_code == 404, (path, response.text)
            assert response.json()["code"] == "EXPORT_NOT_FOUND"
        listed = client.get(f"{API}/exports", headers=_campus(client)).json()["items"]
        assert "exp_test_foreign" not in {item["export_id"] for item in listed}
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM export_jobs WHERE export_id = 'exp_test_foreign'"))


def test_downloading_before_the_worker_runs_is_a_conflict(client) -> None:
    created = _create(client)
    export_id = created["export_id"]
    try:
        response = client.get(f"{API}/exports/{export_id}/download", headers=_campus(client))
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "EXPORT_NOT_READY"
        assert response.json()["details"]["status"] == "PENDING"
    finally:
        _purge(export_id)


def test_listing_is_newest_first_and_limited_to_the_requester(client) -> None:
    first = _create(client)
    second = _create(client, params={**PARAMS, "group_by": "gender"})
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("UPDATE export_jobs SET created_at = now() - interval '1 hour' WHERE export_id = :i"),
                {"i": first["export_id"]},
            )
        items = client.get(f"{API}/exports", headers=_campus(client)).json()
        assert items["next_cursor"] is None
        ids = [item["export_id"] for item in items["items"]]
        # 首条是 second、第二条是 first 会被库里的历史任务打断，这里只锁相对顺序。
        assert ids.index(second["export_id"]) < ids.index(first["export_id"])
    finally:
        _purge(first["export_id"], second["export_id"])


def test_export_is_campus_only(client) -> None:
    before = _export_count()
    for login_name in ("student", "counselor", "dorm"):
        headers = auth(token_for(client, login_name))
        payload = {"report": "STATISTICS", "params": PARAMS}
        for method, path in (("post", ""), ("get", ""), ("get", "/exp_test_foreign")):
            call = getattr(client, method)
            response = call(
                f"{API}/exports{path}",
                headers=headers,
                **({"json": payload} if method == "post" else {}),
            )
            assert response.status_code == 403, (login_name, method, path, response.text)
            assert response.json()["code"] == "FORBIDDEN_ACTION"
    assert _export_count() == before


def test_the_worker_loop_uses_the_same_registry_entry(client) -> None:
    """登记在唯一注册表里的处理器名与队列任务类型必须一致，否则任务会永远停在 PENDING。"""
    assert "EXPORT_BUILD" in HANDLERS
    assert HANDLERS["EXPORT_BUILD"].__name__ == "export_build"
    created = _create(client)
    try:
        from app.worker.main import run_once

        assert run_once(build_clock().now(), timedelta(seconds=60)) >= 1
        assert client.get(f"{API}/exports/{created['export_id']}", headers=_campus(client)).json()[
            "status"
        ] == "DONE"
    finally:
        _purge(created["export_id"])
