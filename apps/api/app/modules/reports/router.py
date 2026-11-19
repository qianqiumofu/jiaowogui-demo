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
from app.modules.identity.schemas import Role, SessionContext
from app.modules.reports import readmodel

router = APIRouter(prefix="/reports", tags=["reports"])

ReadDep = Annotated[SessionContext, Depends(require("report:read"))]
SubscribeDep = Annotated[SessionContext, Depends(require("report:subscribe"))]
SessionDep = Annotated[Session, Depends(get_session)]
ServiceDate = Annotated[
    date | None, Query(description="业务日 YYYY-MM-DD，缺省为当前时刻的前一晚。")
]


def report_scope_note(context: SessionContext) -> str:
    if context.active_role is Role.AUTH_ADMIN:
        return "统计全校授权范围内的学生。"
    if context.active_role is Role.COLLEGE_ADMIN:
        return "只统计获授学院范围内的学生。"
    return readmodel.SCOPE_NOTE_COUNSELOR


@router.get("/daily")
def daily(guarded: ReadDep, db: SessionDep, request: Request, service_date: ServiceDate = None) -> dict:
    clock = request.app.state.clock
    moment = clock.now()
    night = readmodel.resolve_service_date(service_date, now=moment)
    items = readmodel.night_rows(
        db, clock, service_date=night, student_ids=readmodel.student_ids_of(guarded)
    )
    return readmodel.daily_view(items, service_date=night, now=moment, scope_note=report_scope_note(guarded))


@router.get("/weekly")
def weekly(guarded: ReadDep, db: SessionDep, request: Request, service_date: ServiceDate = None) -> dict:
    clock = request.app.state.clock
    moment = clock.now()
    start, end = readmodel.week_window(readmodel.resolve_service_date(service_date, now=moment))
    items = readmodel.range_rows(
        db, clock, start=start, end=end, student_ids=readmodel.student_ids_of(guarded)
    )
    return readmodel.weekly_view(items, start=start, end=end, now=moment, scope_note=report_scope_note(guarded))


@router.get("/subscriptions")
def subscriptions(guarded:SubscribeDep):
    from app.modules.reports.subscriptions import get
    return get(guarded.user_id)

from pydantic import BaseModel
class SubscriptionRequest(BaseModel):
    daily:bool
    weekly:bool

@router.put("/subscriptions")
def update_subscriptions(payload:SubscriptionRequest,guarded:SubscribeDep,db:SessionDep,request:Request):
    from app.modules.reports.subscriptions import save
    return save(db,guarded.user_id,payload.daily,payload.weekly,request.app.state.clock.now())


from app.modules.reports import school_statistics

StatisticsDep = Annotated[SessionContext, Depends(require('report:statistics'))]


def statistics_filters(college_org_id: str = '', grade: str = '', park_org_id: str = '', building_id: str = ''):
    return {'college_org_id': college_org_id, 'grade': grade, 'park_org_id': park_org_id, 'building_id': building_id}


@router.get('/overview')
def school_overview(guarded: StatisticsDep, db: SessionDep, request: Request,
                    filters: Annotated[dict, Depends(statistics_filters)], period: str = 'DAY'):
    return school_statistics.overview(db, guarded, request.app.state.clock, period, filters)


@router.get('/overview/options')
def school_options(guarded: StatisticsDep, db: SessionDep):
    return school_statistics.options(db.connection())


@router.get('/overview/students')
def school_students(guarded: StatisticsDep, db: SessionDep, request: Request,
                    filters: Annotated[dict, Depends(statistics_filters)], dataset: str, period: str = 'DAY',
                    cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return school_statistics.students(db, guarded, request.app.state.clock, period, filters, dataset, cursor, limit)
