"""辅导员报告入口（A 主责）：次日按需查看前一晚与最近一周的情况。

日报、周报邮件由 worker 投递进收件箱，这两个接口是「当场再看一次最新事实」：
取数、排序与计数全部走 `reports.readmodel` 与 `reports.summary`，所以接口数字与
邮件正文不可能各说一套。只读不写，也不产生任何提醒任务（R15）。

负责关系由 B 的目录同步；未同步时 `require("report:read")` 直接 403，不会退化成全校可读。
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import not_implemented
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import SessionContext
from app.modules.reports import readmodel

router = APIRouter(prefix="/reports", tags=["reports"])

ReadDep = Annotated[SessionContext, Depends(require("report:read"))]
SubscribeDep = Annotated[SessionContext, Depends(require("report:subscribe"))]
SessionDep = Annotated[Session, Depends(get_session)]
ServiceDate = Annotated[
    date | None, Query(description="业务日 YYYY-MM-DD，缺省为当前时刻的前一晚。")
]


@router.get("/daily")
def daily(guarded: ReadDep, db: SessionDep, request: Request, service_date: ServiceDate = None) -> dict:
    clock = request.app.state.clock
    moment = clock.now()
    night = readmodel.resolve_service_date(service_date, now=moment)
    items = readmodel.night_rows(
        db, clock, service_date=night, student_ids=readmodel.student_ids_of(guarded)
    )
    return readmodel.daily_view(items, service_date=night, now=moment)


@router.get("/weekly")
def weekly(guarded: ReadDep, db: SessionDep, request: Request, service_date: ServiceDate = None) -> dict:
    clock = request.app.state.clock
    moment = clock.now()
    start, end = readmodel.week_window(readmodel.resolve_service_date(service_date, now=moment))
    items = readmodel.range_rows(
        db, clock, start=start, end=end, student_ids=readmodel.student_ids_of(guarded)
    )
    return readmodel.weekly_view(items, start=start, end=end, now=moment)


@router.get("/subscriptions")
def subscriptions(guarded: SubscribeDep) -> dict:
    # 订阅关系要落表，迁移号排在 B 的头之后，此处继续保持占位。
    raise not_implemented("M4", "报告订阅")
