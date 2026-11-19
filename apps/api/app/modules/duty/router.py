from typing import Annotated
from fastapi import APIRouter,Depends,Request
from pydantic import BaseModel,AwareDatetime
from sqlalchemy.orm import Session
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.audit import append as audit
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import SessionContext,Role
from app.modules.identity.service import person_by_user_id
from app.modules.directory import service as directory
router=APIRouter(prefix="/duty-assignments",tags=["duty"])
Read=Annotated[SessionContext,Depends(require("duty:read"))]
Write=Annotated[SessionContext,Depends(require("duty:assign"))]
DB=Annotated[Session,Depends(get_session)]
class DutyRequest(BaseModel):
    staff_user_id:str
    building_id:str
    shift_start:AwareDatetime
    shift_end:AwareDatetime

@router.get("")
def list_duty(guard:Read):
    rows=directory.duty_rows()
    if guard.active_role is Role.DORM_MANAGER:rows=[r for r in rows if r["staff_user_id"]==guard.user_id]
    elif guard.active_role is not Role.CAMPUS:rows=[]
    return {"items":rows,"next_cursor":None}

@router.post("",status_code=201)
def assign(payload:DutyRequest,guard:Write,db:DB,request:Request):
    person=person_by_user_id(payload.staff_user_id)
    if person is None or Role.DORM_MANAGER not in person.roles:raise ApiError(422,"VALIDATION_FAILED","必须指派有效宿管。",{})
    result=directory.assign_duty(db.connection(),payload.staff_user_id,payload.building_id,payload.shift_start,payload.shift_end)
    audit(db,guard.user_id,"DUTY_ASSIGNED",result["duty_id"],{"staff_user_id":payload.staff_user_id,"building_id":payload.building_id},request.app.state.clock.now());db.commit()
    return result

@router.post("/switch")
def switch(payload:DutyRequest,guard:Write,db:DB,request:Request):
    return assign(payload,guard,db,request)

@router.delete("/{duty_id}")
def revoke(duty_id:str,guard:Write,db:DB,request:Request):
    result=directory.revoke_duty(db.connection(),duty_id,request.app.state.clock.now())
    audit(db,guard.user_id,"DUTY_REVOKED",duty_id,{},request.app.state.clock.now());db.commit();return result
