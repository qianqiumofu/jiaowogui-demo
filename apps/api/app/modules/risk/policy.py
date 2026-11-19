from sqlalchemy import select,update,text
from sqlalchemy.orm import Session
from app.core.db import get_engine
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.audit import append as audit
from app.db.models import PolicyVersion

def current():
    settings=get_settings()
    if settings.database_url:
        with Session(get_engine()) as db:
            row=db.scalar(select(PolicyVersion).where(PolicyVersion.active.is_(True)).order_by(PolicyVersion.created_at.desc()))
            if row:return {"version":row.version,**row.rules}
    return {"version":settings.risk_rule_version,"window_nights":settings.risk_window_nights,"times_threshold":settings.risk_times_threshold,"consecutive_threshold":settings.risk_consecutive_threshold}


def save(db,actor,payload,at):
    # 单一活动版本：串行化并发发布，而不依赖应用进程内锁。
    db.execute(text('SELECT pg_advisory_xact_lock(693112417)'))
    version=payload["version"].strip()
    if not version or len(version)>64 or any(not 1<=payload[k]<=365 for k in ("window_nights","times_threshold","consecutive_threshold")):
        raise ApiError(422,"VALIDATION_FAILED","规则版本及阈值取值不合法。",{})
    if db.get(PolicyVersion,version):raise ApiError(409,"VERSION_CONFLICT","规则版本已存在，不能改写历史版本。",{})
    db.execute(update(PolicyVersion).values(active=False))
    rules={k:payload[k] for k in ("window_nights","times_threshold","consecutive_threshold")}
    db.add(PolicyVersion(version=version,rules=rules,active=True,actor_user_id=actor,created_at=at))
    audit(db,actor,"RISK_POLICY_PUBLISHED",version,rules,at);db.commit()
    return {"version":version,**rules}
