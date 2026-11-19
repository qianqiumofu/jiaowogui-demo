"""统计模块（B 主责）：园区端全校晚归统计与筛选器选项。"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.clock import service_date_of
from app.core.db import get_engine, get_session
from sqlalchemy.orm import Session
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import SessionContext
from app.modules.statistics import service

router = APIRouter(prefix="/statistics", tags=["statistics"])

StatisticsDep = Annotated[SessionContext, Depends(require("statistics:read"))]
FiltersDep = Annotated[SessionContext, Depends(require("statistics:read"))]

# 缺省区间：园区端默认看近两周的趋势。取 14 夜有两个理由——当晚多为零，
# 且窗口长于「一人一夜最多一条」的重复周期，首屏就能看到人数与晚归夜数不相等。
DEFAULT_RANGE_NIGHTS = 14


@router.get('/quick')
def quick_statistics(context: StatisticsDep, request: Request,
                     db: Annotated[Session, Depends(get_session)], period: str = 'DAY',
                     college_org_id: str = '', grade: str = '', education_level: str = '', park_org_id: str = '', building_id: str = ''):
    return service.quick_overview(db, context, request.app.state.clock, period,
        {'college_org_id': college_org_id, 'grade': grade, 'education_level': education_level, 'park_org_id': park_org_id, 'building_id': building_id})


@router.get("")
def statistics(
    context: StatisticsDep,
    request: Request,
    date_to: str | None = None,
    date_from: str | None = None,
    college_org_id: str | None = None,
    park_org_id: str | None = None,
    building_id: str | None = None,
    grade: str | None = None,
    education_level: str | None = None,
    gender: str | None = None,
    return_source: str | None = None,
    group_by: str = "park",
    attribution: str = "snapshot",
) -> dict:
    """全校晚归三值统计（R14）：人数、晚归夜数、返宿次数分列，园区范围固定全校。

    只给一个日期时统计那一夜；两个都缺省时统计当前业务夜往前 `DEFAULT_RANGE_NIGHTS` 夜。
    口径见基线「园区统计口径」。
    """
    current_night = service_date_of(request.app.state.clock.now())
    if date_to is None and date_from is None:
        date_from = (current_night - timedelta(days=DEFAULT_RANGE_NIGHTS - 1)).isoformat()
        date_to = current_night.isoformat()
    else:
        fallback = current_night.isoformat()
        date_from = date_from or date_to or fallback
        date_to = date_to or date_from
    with get_engine().connect() as conn:
        return service.query(
            conn,
            date_from=date_from,
            date_to=date_to,
            college_org_id=college_org_id,
            park_org_id=park_org_id,
            building_id=building_id,
            grade=grade,
            education_level=education_level,
            gender=gender,
            return_source=return_source,
            group_by=group_by,
            attribution=attribution,
            allowed=service.allowed_students(context),
        )


@router.get("/filters")
def statistics_filters(context: FiltersDep) -> dict:
    """筛选器选项：学院、片区（含楼栋数）、楼栋、年级、性别、晚归来源。

    选项按调用者权限范围收窄：辅导员/学院负责人只看到自己负责范围内实际存在的目录。
    """
    with get_engine().connect() as conn:
        return service.filters(conn, service.allowed_students(context))
