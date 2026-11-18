from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class NotificationTemplate(str, Enum):
    """与 `service.TEMPLATES` 一一对应；新增模板必须同时加正文与越权测试。"""

    NIGHT_ROSTER = "NIGHT_ROSTER"
    DAILY_REPORT = "DAILY_REPORT"
    WEEKLY_REPORT = "WEEKLY_REPORT"
    RISK_ALERT = "RISK_ALERT"


class DispatchRequest(BaseModel):
    """演示投递：只有园区能调，收件人与范围在正式版由目录派生，不由请求指定。"""

    template: NotificationTemplate
    service_date: date | None = None
    recipient_user_ids: list[str] = Field(min_length=1)
    student_ids: list[str] | None = None
    deliver_now: bool = False
