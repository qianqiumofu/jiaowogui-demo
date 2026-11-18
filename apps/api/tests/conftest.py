"""共享夹具。

数据库约定：需要真实 PostgreSQL 的测试显式依赖 `postgres_schema`。
- 已设置 `JWG_TEST_DATABASE_URL` 或 .env 中的 `DATABASE_URL` 可连通时才会运行；
- 未提供时明确 skip，而不是放宽断言凑全绿。
- 本机开发库（容器 `jiaowogui-postgres`）跑常规回归必须带
  `JWG_TEST_DATABASE_URL`，见 docs/01。
"""

import os
from collections.abc import Iterator
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
    with TestClient(create_app()) as test_client:
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
    env_file = API_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


@pytest.fixture(scope="session")
def postgres_schema() -> str:
    """把迁移升到头并返回连接串；无可用数据库时明确 skip。"""
    url = _resolve_test_database_url()
    if url is None:
        pytest.skip("未配置 JWG_TEST_DATABASE_URL 或 apps/api/.env 的 DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    from app.core.config import get_settings

    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - 连不上就 skip，不算失败
        pytest.skip(f"PostgreSQL 不可用：{exc}")
    return url


@pytest.fixture()
def clean_db(postgres_schema: str) -> Iterator[None]:
    """每个测试前清空业务表，防止用例互串。"""
    from sqlalchemy import text
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE reservations, reservation_revisions, local_staff_accounts, "
                "notifications, background_jobs RESTART IDENTITY"
            )
        )
    yield
