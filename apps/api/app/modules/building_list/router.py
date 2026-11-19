"""楼栋名单模块（B 主责）：仅有效值班楼栋可见，24:00 汇总后实时标异动。"""

from typing import Annotated
from datetime import date

from fastapi import APIRouter, Depends, Request

from app.modules.authorization.dependencies import require
from app.modules.building_list import service
from app.modules.identity.schemas import SessionContext

router = APIRouter(prefix="/buildings", tags=["building-list"])

TonightDep = Annotated[SessionContext, Depends(require("building:tonight"))]
campus_router = APIRouter(prefix='/campus', tags=['building-list'])
CampusDep = Annotated[SessionContext, Depends(require('campus:query'))]


@campus_router.get('/night-summary')
def campus_night_summary(context: CampusDep, request: Request, service_date: date | None = None,
                         park_org_id: str | None = None, building_id: str | None = None):
    return service.night_summary(request.app.state.clock.now(), service_date, park_org_id, building_id)


@router.get("/{building_id}/tonight")
def tonight(building_id: str, context: TonightDep, request: Request) -> dict:
    service.ensure_building_in_scope(context.scope, building_id)
    return service.tonight(building_id, request.app.state.clock.now())
