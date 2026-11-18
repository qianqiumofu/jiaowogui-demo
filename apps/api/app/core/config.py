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
    # 仅模拟统一身份的种子账号；园区注册的工号账号各有独立口令（R19）。
    demo_login_password: str = "demo1234"

    # 通知调度与风险提示的取值全部是「Demo 工程默认」，正式值待学校确认（基线 R16 行）。
    # 时间一律 HH:MM，按业务时区解释；周期任务只能由 worker 读取，不在请求里判定。
    roster_snapshot_at: str = "23:30"
    daily_report_at: str = "08:30"
    weekly_report_at: str = "09:00"
    weekly_report_weekday: int = 0
    weekly_report_nights: int = 7
    risk_window_nights: int = 7
    risk_times_threshold: int = 3
    risk_consecutive_threshold: int = 3
    # 规则集版本随阈值一起变更；弹窗与提示都要落它，便于事后解释「按哪一版算的」。
    risk_rule_version: str = "DEMO-2026.11"


@lru_cache
def get_settings() -> Settings:
    return Settings()
