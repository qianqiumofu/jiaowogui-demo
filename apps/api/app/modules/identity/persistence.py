"""持久会话仅存随机令牌摘要，支持多进程恢复与职责撤回。"""
import hashlib
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.core.db import get_engine
from app.db.models import IdentitySession


def digest(token): return hashlib.sha256(token.encode()).hexdigest()


def save(record, now):
    with Session(get_engine()) as db:
        db.add(IdentitySession(id=record.session_id,token_digest=digest(record.token),user_id=record.user_id,
                              role=record.active_role.value,expires_at=record.expires_at,created_at=now))
        db.commit()


def find(token=None, session_id=None):
    with Session(get_engine()) as db:
        row=db.scalar(select(IdentitySession).where(IdentitySession.token_digest==digest(token))) if token else db.get(IdentitySession,session_id)
        if row is None:return None
        return {"session_id":row.id,"user_id":row.user_id,"role":row.role,"expires_at":row.expires_at}


def drop(session_id=None,user_id=None):
    with Session(get_engine()) as db:
        query=delete(IdentitySession)
        query=query.where(IdentitySession.id==session_id) if session_id else query.where(IdentitySession.user_id==user_id)
        db.execute(query);db.commit()


def cleanup_expired_sessions(now):
    with Session(get_engine()) as db:
        db.execute(delete(IdentitySession).where(IdentitySession.expires_at<=now));db.commit()
