"""模拟现场核验：服务端窗口、负责身份、一次凭证和签码在同一事务中完成。"""
import secrets
from sqlalchemy.orm import Session
from app.core.clock import business_iso
from app.core.errors import ApiError
from app.core.audit import append as audit
from app.db.models import VerificationSession
from app.modules.reservation import service as reservation
from app.modules.directory import service as directory
from app.modules.access import service as access
from app.modules.verification.windows import window_of


def verify(db:Session,clock,context,reservation_id,expected_version,face_result,presence_result):
    now=clock.now()
    res=reservation._load_owned(db,clock,reservation_id=reservation_id,scope={"student_id":context.scope["student_id"]},resolved_by="identity")
    reservation._assert_mutable(res,expected_version)
    window=window_of(res.planned_return_at)
    if not window.contains(now):
        raise ApiError(409,"VERIFICATION_WINDOW_CLOSED","当前不在服务端核验窗口。",{"opens_at":business_iso(window.opens_at),"closes_at":business_iso(window.closes_at)})
    home=directory.get_residence(res.student_id,now)
    if home is None:raise ApiError(403,"SCOPE_UNRESOLVED","住宿关系未同步。",{})
    row=VerificationSession(id="vs_"+secrets.token_hex(10),reservation_id=res.id,student_id=res.student_id,reservation_version=res.version,
        status="SUCCEEDED" if face_result and presence_result else "FAILED",face_result=face_result,presence_result=presence_result,created_at=now)
    db.add(row);db.flush()
    if row.status=="FAILED":
        audit(db,context.user_id,"VERIFICATION_FAILED",row.id,{"simulated":True},now);db.commit()
        raise ApiError(422,"VERIFICATION_FAILED","模拟核验未通过，未签发二维码。",{"verification_id":row.id,"simulated":True})
    issued=access.issue_pass(res.id,res.version,{"student_id":res.student_id,"building_id":home["building_id"],"verification_id":row.id,
        "verified_at":business_iso(now),"planned_return_at":business_iso(res.planned_return_at),"window_start":business_iso(window.opens_at),"window_end":business_iso(window.closes_at)},conn=db.connection())
    row.pass_id=issued["pass_id"];row.consumed_at=now
    audit(db,context.user_id,"VERIFICATION_CONSUMED",row.id,{"pass_id":row.pass_id,"simulated":True},now)
    # 本地 SVG 编码，不存 token 明文，不调用外部图片服务。
    import qrcode
    from qrcode.image.svg import SvgPathImage
    issued["qr_svg"]=qrcode.make(issued["token"],image_factory=SvgPathImage).to_string().decode("utf-8")
    db.commit()
    return {"verification_id":row.id,"status":row.status,"simulated":True,"pass":issued}


def consume_grant(conn,verification_id,reservation_id,version,student_id,res,planned_return_at,verified_at):
    from sqlalchemy import text
    proof=conn.execute(text("SELECT * FROM verification_sessions WHERE id=:id FOR UPDATE"),{"id":verification_id}).mappings().first()
    if proof is None or proof["status"]!="SUCCEEDED" or proof["consumed_at"] is not None:
        raise ApiError(409,"VERIFICATION_ALREADY_USED","核验凭证不存在、失败或已经消费。",{})
    if proof["reservation_id"]!=reservation_id or proof["reservation_version"]!=version or proof["student_id"]!=student_id or res["student_id"]!=student_id or res["planned_return_at"]!=planned_return_at:
        raise ApiError(409,"VERSION_CONFLICT","核验凭证与预约绑定不一致。",{})
    if not window_of(res["planned_return_at"]).contains(verified_at):raise ApiError(409,"VERIFICATION_WINDOW_CLOSED","核验时刻不在预约窗口。",{})
    conn.execute(text("UPDATE verification_sessions SET consumed_at=:at WHERE id=:id"),{"at":verified_at,"id":verification_id})


def attach_pass(conn,verification_id,pass_id):
    from sqlalchemy import text
    conn.execute(text("UPDATE verification_sessions SET pass_id=:p WHERE id=:id"),{"p":pass_id,"id":verification_id})
