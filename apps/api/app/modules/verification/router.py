from typing import Annotated
from fastapi import APIRouter,Depends,Request
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.core.db import get_session
from app.core.errors import ApiError
from app.db.models import VerificationSession
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import SessionContext
from app.modules.verification import service
router=APIRouter(prefix="/verification-sessions",tags=["verification"])
Guard=Annotated[SessionContext,Depends(require("verification:create"))]
DB=Annotated[Session,Depends(get_session)]
class VerifyRequest(BaseModel):
    reservation_id:str
    expected_version:int=Field(ge=1)
    face_result:bool
    presence_result:bool

@router.post("",status_code=201)
def verify(payload:VerifyRequest,guard:Guard,db:DB,request:Request):
    return service.verify(db,request.app.state.clock,guard,**payload.model_dump())

@router.get("/{verification_id}")
def read(verification_id:str,guard:Guard,db:DB,request:Request):
    row=db.get(VerificationSession,verification_id)
    if row is None or row.student_id!=guard.scope.get("student_id"):
        raise ApiError(404,"SUBJECT_NOT_FOUND","核验不存在或不属于本人。",{})
    from app.modules.access.service import pass_view
    return {"verification_id":row.id,"status":row.status,"pass_id":row.pass_id,"consumed_at":row.consumed_at,"simulated":True,**(pass_view(row.pass_id,request.app.state.clock.now()) if row.pass_id else {})}
