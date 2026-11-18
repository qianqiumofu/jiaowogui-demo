"""worker 处理器注册：通知投递（A 主责）。

只有 worker 进程会加载本模块；API 进程入队后不投递，见 `app/worker/main.py`。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.clock import build_clock
from app.core.db import get_engine
from app.modules.notification import service
from app.worker.registry import handler


@handler("NOTIFICATION_SEND")
def send_notification(job: dict) -> None:
    session = Session(get_engine())
    try:
        service.deliver(
            session,
            build_clock(),
            job_id=job["id"],
            business_key=job["business_key"],
            payload=job["payload"],
        )
    finally:
        session.close()
