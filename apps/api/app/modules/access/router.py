"""通行核销接口（B 主责）：终端按设备身份鉴权，不用学生会话。

签码与撤销不开放 HTTP 入口：A 的核验链路直接调用 `access.service`，避免绕过核验领码。
"""

from fastapi import APIRouter, Header, Request

from app.core.errors import ApiError
from app.modules.access import service

router = APIRouter(prefix="/device", tags=["access"])


@router.post("/scan")
def scan(
    payload: dict,
    request: Request,
    device_id: str = Header(..., alias="x-device-id"),
    device_token: str = Header(..., alias="x-device-token"),
) -> dict:
    """扫码核销：成功即在统一事务里落一条正式返宿记录，重复扫码返回同一条。"""
    code = payload.get("code")
    if not isinstance(code, str) or not code:
        raise ApiError(
            422, "VALIDATION_FAILED", "扫码内容缺少二维码。", {"missing": "code"}
        )
    return service.consume(device_id, device_token, code, request.app.state.clock.now(),result=payload.get("result","SUCCEEDED"),reconcile_result=payload.get("reconcile_result","SUCCEEDED"))


from pydantic import BaseModel,AwareDatetime,Field
from typing import Literal
integration_router=APIRouter(prefix="/integrations/access",tags=["access"])
class ReceiptRequest(BaseModel):
    event_id:str=Field(min_length=1,max_length=128)
    attempt_id:str
    status:Literal["SUCCEEDED","FAILED","UNKNOWN"]
    occurred_at:AwareDatetime

@integration_router.post("/events")
def receive(payload:ReceiptRequest,request:Request,device_id:str=Header(...,alias="x-device-id"),device_token:str=Header(...,alias="x-device-token")):
    from app.modules.access.receipts import apply
    return apply(device_id,device_token,**payload.model_dump(),now=request.app.state.clock.now())
