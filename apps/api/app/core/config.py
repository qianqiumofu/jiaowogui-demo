from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # 相对 env_file 按启动目录解析；文档里的 `--app-dir apps/api` 从仓库根启动，
    # 那一层看不到 apps/api/.env，所以补一条按包位置定位的绝对路径。
    model_config = SettingsConfigDict(
        env_file=(API_ROOT / ".env", ".env", "../../.env"), extra="ignore"
    )

    app_name: str = "jiaowogui-api"
    business_timezone: str = "Asia/Shanghai"
    database_url: str | None = None
    session_ttl_minutes: int = 4320
    reservation_reason_max_chars: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
