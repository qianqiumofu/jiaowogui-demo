from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_engine
from app.db.models import ReportSubscription

def get(user_id):
    with Session(get_engine()) as db:
        row=db.get(ReportSubscription,user_id)
        return {"daily":row.daily if row else False,"weekly":row.weekly if row else False}

def save(db,user_id,daily,weekly,at):
    row=db.get(ReportSubscription,user_id)
    if row is None:row=ReportSubscription(user_id=user_id,updated_at=at);db.add(row)
    row.daily=daily;row.weekly=weekly;row.updated_at=at;db.commit()
    return {"daily":row.daily,"weekly":row.weekly}

def enabled():
    with Session(get_engine()) as db:
        return [{"user_id":r.user_id,"daily":r.daily,"weekly":r.weekly,"updated_at":r.updated_at} for r in db.scalars(select(ReportSubscription))]
