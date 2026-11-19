from typing import Annotated
from fastapi import APIRouter,Depends,Request
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.core.db import get_session
from app.modules.authorization.dependencies import require
from app.modules.identity.schemas import SessionContext
from app.modules.risk import events,policy
router=APIRouter(tags=["risk"])
Read=Annotated[SessionContext,Depends(require("risk:read"))]
Act=Annotated[SessionContext,Depends(require("risk:ack"))]
FollowUp=Annotated[SessionContext,Depends(require('risk:follow_up'))]
Config=Annotated[SessionContext,Depends(require("risk:config"))]
DB=Annotated[Session,Depends(get_session)]
class Note(BaseModel):
    note:str=Field(min_length=1,max_length=500)
class FollowUpNote(Note):
    idempotency_key:str=Field(min_length=1,max_length=128)
class Policy(BaseModel):
    version:str=Field(min_length=1,max_length=64)
    window_nights:int=Field(ge=1,le=365)
    times_threshold:int=Field(ge=1,le=365)
    consecutive_threshold:int=Field(ge=1,le=365)

@router.get("/risk-events")
def list_events(guard:Read,db:DB,status:str|None=None):return events.list_events(db,guard,status)
@router.post("/risk-events/{event_id}/ack")
def ack(event_id:str,payload:Note,guard:Act,db:DB,request:Request):return events.act(db,guard,event_id,"ACK",payload.note,request.app.state.clock.now())
@router.post("/risk-events/{event_id}/resolve")
def resolve(event_id:str,payload:Note,guard:Act,db:DB,request:Request):return events.act(db,guard,event_id,"RESOLVE",payload.note,request.app.state.clock.now())
@router.post('/risk-events/{event_id}/follow-up')
def follow_up(event_id:str,payload:FollowUpNote,guard:FollowUp,db:DB,request:Request):
    return events.act(db,guard,event_id,'FOLLOW_UP',payload.note,request.app.state.clock.now(),payload.idempotency_key)
@router.get("/risk-policy")
def current(guard:Config):return policy.current()
@router.put("/risk-policy")
def update(payload:Policy,guard:Config,db:DB,request:Request):return policy.save(db,guard.user_id,payload.model_dump(),request.app.state.clock.now())
