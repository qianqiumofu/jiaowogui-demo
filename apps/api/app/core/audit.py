"""只追加审计；不保存口令、二维码明文、人脸或真实外部身份资料。"""
import secrets
from app.db.models import AuditLog

def append(session, actor, action, target, payload, at):
    row = AuditLog(id="aud_"+secrets.token_hex(12), actor_user_id=actor, action=action,
                   target=target, payload=payload, created_at=at)
    session.add(row)
    return row
