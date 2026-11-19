"""共享夹具。

数据库约定：需要真实 PostgreSQL 的测试显式依赖 `postgres_schema`。
- 仅显式设置指向隔离测试库的 `JWG_TEST_DATABASE_URL` 时运行；
- 未提供时明确 skip，而不是放宽断言凑全绿。
- 本机开发库（容器 `jiaowogui-postgres`）跑常规回归必须带
  `JWG_TEST_DATABASE_URL`，见 docs/01。
"""

import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

API = "/api/v1"
PASSWORD = "demo1234"

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_demo_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """每个用例用独立的演示时钟文件，防止一个用例推进的偏移漏进下一个。"""
    from app.core.config import get_settings

    monkeypatch.setenv("DEMO_CLOCK_FILE", str(tmp_path / "demo_clock.json"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client(isolated_demo_clock: None) -> Iterator[TestClient]:
    app=create_app()
    with TestClient(app) as test_client:
        if os.environ.get("JWG_TEST_DATABASE_URL"):
            from zoneinfo import ZoneInfo
            # 申请用例固定在开放时段，避免测试运行过午夜时与真实墙钟竞争。
            app.state.clock.offset=datetime(2026,11,15,18,tzinfo=ZoneInfo("Asia/Shanghai"))-datetime.now(ZoneInfo("Asia/Shanghai"))
        yield test_client


def token_for(client: TestClient, login_name: str) -> str:
    response = client.post(
        f"{API}/auth/mock-login", json={"login_name": login_name, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def student_token(client: TestClient) -> str:
    return token_for(client, "student")


def _resolve_test_database_url() -> str | None:
    url = os.environ.get("JWG_TEST_DATABASE_URL")
    if url:
        return url
    return None


@pytest.fixture(scope="session")
def postgres_schema() -> str:
    """把迁移升到头并返回连接串；无可用数据库时明确 skip。"""
    url = _resolve_test_database_url()
    if url is None:
        pytest.skip("未配置隔离 JWG_TEST_DATABASE_URL")
    from sqlalchemy.engine import make_url
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("JWG_TEST_DATABASE_URL 必须指向名称以 _test 结尾的隔离测试库")
    os.environ["DATABASE_URL"] = url
    from app.core.config import get_settings

    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(cfg, "head")  # 已配置数据库时，迁移/连接失败必须使验收失败。
    return url


@pytest.fixture()
def clean_db(seeded_demo_db: str) -> Iterator[None]:
    """每个测试前清空业务表，防止用例互串。"""
    from sqlalchemy import text
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        for name in ("return_evidence","risk_actions","risk_events","return_corrections","access_receipts","passage_attempts","verification_sessions","report_subscriptions","policy_versions","audit_logs","notifications", "background_jobs", "return_records", "pass_codes", "reservation_revisions", "reservations"):
            conn.execute(text(f"DELETE FROM {name}"))
        conn.execute(text("DELETE FROM identity_sessions WHERE user_id NOT LIKE 'usr_synth_%'"))
        conn.execute(text("DELETE FROM role_assignments WHERE user_id NOT LIKE 'usr_synth_%'"))
        conn.execute(text("DELETE FROM users WHERE source='STAFF_LOCAL' AND user_id NOT LIKE 'usr_synth_%'"))
    yield


def jump_clock(client: TestClient, hour: int, minute: int = 0) -> datetime:
    """把演示时钟推进到下一个 HH:MM，让值班与 24:00 边界测试不受真实钟点影响。

    `/demo/clock` 写入的是绝对偏移，因此目标相对未平移的真实时间计算，可连续跳转。
    """
    payload = client.get(f"{API}/demo/clock").json()
    real_now = datetime.fromisoformat(payload["now"]) - timedelta(
        minutes=payload["offset_minutes"]
    )
    current=datetime.fromisoformat(payload["now"])
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    offset = int((target - real_now).total_seconds() // 60)
    response = client.post(f"{API}/demo/clock", json={"offset_minutes": offset})
    assert response.status_code == 200, response.text
    return datetime.fromisoformat(response.json()["now"])


@pytest.fixture(scope="module")
def seeded_demo_db(postgres_schema: str) -> str:
    """仅在隔离测试库中重置合成数据，禁止误清开发库。"""
    from sqlalchemy.engine import make_url
    from app.core.db import get_engine
    from app.db.seed import seed
    from datetime import date
    if not (make_url(postgres_schema).database or "").endswith("_test"):
        pytest.fail("测试会重置合成数据，请配置名称以 _test 结尾的隔离 JWG_TEST_DATABASE_URL")
    engine = get_engine()
    from app.db.base import Base
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    seed(engine, date(2026, 11, 15), "Asia/Shanghai")
    # seed 的快照任务是演示数据；各测试独立安排自己的任务。
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE background_jobs CASCADE"))
    return postgres_schema
