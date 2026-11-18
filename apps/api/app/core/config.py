from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_name: str = "jiaowogui-api"
    business_timezone: str = "Asia/Shanghai"
    database_url: str | None = None
    session_ttl_minutes: int = 4320
    dorm_summary_at: str = "24:00"
    pass_ttl_seconds: int = 300
    export_retention_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
