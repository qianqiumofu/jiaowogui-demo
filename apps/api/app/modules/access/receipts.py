"""设备回执与模拟对账：未知保持占用，只有成功证据才写正式返宿。"""
import json,secrets,hashlib
from datetime import timedelta
from sqlalchemy import text
from app.core.db import get_engine
from app.core.night_lock import lock_night
from app.core.clock import service_date_of,business_iso
from app.core.config import get_settings
from app.core.errors import ApiError
from app.modules.returns import service as returns


def attempt_by_pass(conn,pass_id):
    row=conn.execute(text("SELECT * FROM passage_attempts WHERE pass_id=:p"),{"p":pass_id}).mappings().first()
    return dict(row) if row else None


def start(conn,pass_row,device_id,at,status,mock_result):
    if status not in ("SUCCEEDED","FAILED","UNKNOWN") or mock_result not in ("SUCCEEDED","FAILED"):
        raise ApiError(422,"VALIDATION_FAILED","模拟设备结果只能是成功、失败或未知。",{})
    attempt_id="att_"+secrets.token_hex(10)
    conn.execute(text("INSERT INTO passage_attempts(id,pass_id,device_id,student_id,service_date,status,mock_result,requested_at,updated_at) VALUES(:id,:p,:dev,:s,:d,:status,:result,:at,:at)"),
        {"id":attempt_id,"p":pass_row["pass_id"],"dev":device_id,"s":pass_row["student_id"],"d":pass_row["service_date"],"status":status,"result":mock_result,"at":at})
    if status=="FAILED":conn.execute(text("UPDATE pass_codes SET status='REVOKED' WHERE pass_id=:p"),{"p":pass_row["pass_id"]})
    if status=="UNKNOWN":
        from app.worker.scheduler import enqueue
        enqueue(conn,"DEVICE_RECONCILE","DEVICE_RECONCILE:"+attempt_id,{"attempt_id":attempt_id},at+timedelta(seconds=get_settings().device_reconcile_seconds))
    conn.execute(text("INSERT INTO access_receipts(id,event_id,attempt_id,status,occurred_at,received_at) VALUES(:id,:event,:attempt,:status,:at,:at)"),
        {"id":"rcpt_"+secrets.token_hex(12),"event":"scan:"+attempt_id,"attempt":attempt_id,"status":status,"at":at})
    return attempt_id


def apply(device_id,device_token,event_id,attempt_id,status,occurred_at,now):
    from app.modules.access.service import authenticate_device
    device=authenticate_device(device_id,device_token)
    return _apply(device, event_id,attempt_id,status,occurred_at,now)


def _apply(device,event_id,attempt_id,status,occurred_at,now):
    with get_engine().begin() as conn:
        attempt=conn.execute(text("SELECT * FROM passage_attempts WHERE id=:id"),{"id":attempt_id}).mappings().first()
        if attempt is None:raise ApiError(404,"SUBJECT_NOT_FOUND","通行尝试不存在。",{})
        if attempt["device_id"]!=device["device_id"]:raise ApiError(403,"DEVICE_UNAUTHORIZED","终端不能回执别的设备尝试。",{})
        if occurred_at>now or occurred_at<attempt["requested_at"] or service_date_of(occurred_at)!=attempt["service_date"]:
            raise ApiError(422,"VALIDATION_FAILED","回执发生时间不属于已授权的原业务夜。",{})
        lock_night(conn,attempt["student_id"],attempt["service_date"])
        attempt=conn.execute(text("SELECT * FROM passage_attempts WHERE id=:id FOR UPDATE"),{"id":attempt_id}).mappings().one()
        replay=conn.execute(text("SELECT * FROM access_receipts WHERE event_id=:id"),{"id":event_id}).mappings().first()
        if replay and (replay["attempt_id"]!=attempt_id or replay["status"]!=status or replay["occurred_at"]!=occurred_at):
            raise ApiError(409,"VERSION_CONFLICT","回执幂等键已用于不同内容。",{})
        if attempt["status"] in ("SUCCEEDED","FAILED") and attempt["status"]!=status:
            raise ApiError(409,"VERSION_CONFLICT","已完成尝试不能被相反回执覆盖。",{})
        if not replay:
            conn.execute(text("INSERT INTO access_receipts(id,event_id,attempt_id,status,occurred_at,received_at) VALUES(:id,:event,:attempt,:status,:at,:now)"),
                {"id":"rcpt_"+secrets.token_hex(12),"event":event_id,"attempt":attempt_id,"status":status,"at":occurred_at,"now":now})
        returned=None
        if status=="SUCCEEDED":
            code=conn.execute(text("SELECT * FROM pass_codes WHERE pass_id=:p"),{"p":attempt["pass_id"]}).mappings().one()
            returned=returns.confirm_return(conn,attempt["student_id"],attempt["service_date"],"QR",{"receipt_event_id":event_id,"attempt_id":attempt_id,"device_id":device["device_id"]},occurred_at,"receipt:"+hashlib.sha256(event_id.encode()).hexdigest(),pass_id=code["pass_id"],gate_id=device["gate_id"],recorded_at=now)
        elif status=="FAILED":conn.execute(text("UPDATE pass_codes SET status='REVOKED' WHERE pass_id=:p"),{"p":attempt["pass_id"]})
        conn.execute(text("UPDATE passage_attempts SET status=:s,updated_at=:at WHERE id=:id"),{"s":status,"at":now,"id":attempt_id})
        return {"attempt_id":attempt_id,"attempt_status":status,"return_id":returned,"duplicate":bool(replay),"occurred_at":business_iso(occurred_at)}


def reconcile(attempt_id,now):
    # 模拟网关查询使用已记录的演示结果；未知码始终不恢复为 ISSUED。
    with get_engine().connect() as conn:
        attempt=conn.execute(text("SELECT * FROM passage_attempts WHERE id=:id"),{"id":attempt_id}).mappings().first()
    if attempt is None or attempt["status"]!="UNKNOWN":return
    from app.modules.access.service import authenticate_device
    device=authenticate_device(attempt["device_id"],"dev_synth:"+attempt["device_id"])
    _apply(device,"reconcile:"+attempt_id,attempt_id,attempt["mock_result"],attempt["requested_at"],now)
