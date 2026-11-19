from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.config import get_settings
from app.modules.agent import provider, service
from app.modules.agent.schemas import ReportRequest
from app.modules.authorization.dependencies import require
from app.modules.identity.dependencies import get_session_context
from app.modules.identity.schemas import SessionContext

router = APIRouter(prefix='/agent', tags=['agent'])
Guarded = Annotated[SessionContext, Depends(require('agent:use'))]


@router.get('/status')
def agent_status(guarded: Guarded):
    return provider.status(get_settings())


@router.post('/reports')
def report_agent(payload: ReportRequest, guarded: Guarded, request: Request):
    return service.run(guarded, request.app.state.clock, get_settings(), payload,
                       lambda: get_session_context(request, request.headers.get('authorization')))
