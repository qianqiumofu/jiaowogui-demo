"""配置发现：按文档命令从仓库根启动时也要读到 apps/api/.env。"""

import pytest

from app.core.config import API_ROOT, Settings, get_settings

REPO_ROOT = API_ROOT.parent.parent


def test_env_file_search_uses_package_location() -> None:
    first = Settings.model_config["env_file"][0]
    assert first == API_ROOT / ".env"
    assert first.is_absolute()


def test_launch_from_repo_root_sees_api_env(monkeypatch) -> None:
    if not (API_ROOT / ".env").is_file():
        pytest.skip("本机未配置 apps/api/.env")
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().database_url
    finally:
        get_settings.cache_clear()
