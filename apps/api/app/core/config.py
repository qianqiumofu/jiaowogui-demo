from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

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
    # 演示时钟的偏移量落在这个文件里，API 与 worker 读同一个值；相对路径按 apps/api 根解析。
    demo_clock_file: str = ".demo_clock.json"
    # 仅模拟统一身份的种子账号；园区注册的工号账号各有独立口令（R19）。
    demo_login_password: str = "demo1234"

    # 通知调度与风险提示的取值全部是「Demo 工程默认」，正式值待学校确认（基线 R16 行）。
    # 时间一律 HH:MM，按业务时区解释；周期任务只能由 worker 读取，不在请求里判定。
    # `dorm_summary_at` 是业务夜 D 的名单汇总时刻，同时是 D 那一夜的首次申请截止（R12）；
    # `24:00` 即 D+1 00:00，判定统一走 app.core.clock.summary_moment。
    dorm_summary_at: str = "24:00"
    daily_report_at: str = "08:30"
    weekly_report_at: str = "09:00"
    weekly_report_weekday: int = 0
    weekly_report_nights: int = 7
    # 校级周/月多次晚归展示阈值，仅查询分组，不触发风险或通知（Demo 默认）。
    report_repeat_min_nights: int = Field(default=2, ge=2)
    risk_window_nights: int = 7
    risk_times_threshold: int = 3
    risk_consecutive_threshold: int = 3
    # 规则集版本随阈值一起变更；弹窗与提示都要落它，便于事后解释「按哪一版算的」。
    risk_rule_version: str = "DEMO-2026.11"

    # 核验窗口与二维码时长是校方已确认规则（基线 R08 前后 30 分钟、R09 完整 300 秒），
    # 但取值仍只允许在这里配置，业务分支不得写死分钟数。
    verification_margin_minutes: int = 30
    pass_code_seconds: int = 300
    export_retention_days: int = 7
    worker_batch_size: int = 50
    worker_retry_base_seconds: int = 30
    worker_retry_max_seconds: int = 1800
    worker_max_attempts: int = 8
    schedule_lookback_days: int = 2
    risk_evaluation_at: str = "09:30"
    cleanup_at: str = "07:00"
    device_reconcile_seconds: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
