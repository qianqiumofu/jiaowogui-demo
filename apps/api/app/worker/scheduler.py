"""只有 worker 调用的滚动计划；业务键唯一，重启/重放不重复排队。"""
import secrets
from datetime import datetime,time,timedelta
from sqlalchemy import text
from app.core.clock import service_date_of,summary_moment
from app.core.config import get_settings
from app.core.db import get_engine
from app.modules.directory.service import snapshot_buildings
from app.modules.reports.subscriptions import enabled
from app.modules.notification.service import planned_at


def enqueue(conn,kind,key,payload,planned):
    import json
    conn.execute(text("INSERT INTO background_jobs(id,job_type,business_key,payload,planned_at,status,attempts) VALUES (:id,:kind,:key,CAST(:payload AS jsonb),:at,'PENDING',0) ON CONFLICT(business_key) DO NOTHING"),
        {"id":"job_"+secrets.token_hex(12),"kind":kind,"key":key,"payload":json.dumps(payload),"at":planned})


def schedule_due(clock):
    now=clock.now();settings=get_settings();current=service_date_of(now)
    buildings=snapshot_buildings(now);subscriptions=enabled()
    with get_engine().begin() as conn:
        for offset in range(settings.schedule_lookback_days+1):
            night=current-timedelta(days=offset)
            for building in buildings:
                enqueue(conn,"DORM_TONIGHT_SNAPSHOT",f"DORM_TONIGHT_SNAPSHOT:{building}:{night}",{"building_id":building,"service_date":str(night)},summary_moment(night,now.tzinfo))
            for item in subscriptions:
                for template,kind,flag in [("DAILY_REPORT","COUNSELOR_DAILY_REPORT","daily"),("WEEKLY_REPORT","COUNSELOR_WEEKLY_REPORT","weekly")]:
                    if not item[flag]:continue
                    if flag=="weekly" and (night+timedelta(days=1)).weekday()!=settings.weekly_report_weekday:continue
                    if planned_at(template,night,now)<item["updated_at"]:continue
                    enqueue(conn,kind,f"{kind}:{item['user_id']}:{night}",{"template":template,"service_date":str(night),"recipient_user_ids":[item["user_id"]]},planned_at(template,night,now))
            day=night+timedelta(days=1)
            h,m=map(int,settings.risk_evaluation_at.split(":"))
            enqueue(conn,"RISK_PERIODIC_EVALUATION",f"RISK_PERIODIC_EVALUATION:{night}",{"service_date":str(night)},datetime.combine(day,time(h,m),now.tzinfo))
        h,m=map(int,settings.cleanup_at.split(":"))
        enqueue(conn,"DATA_RETENTION_CLEANUP",f"DATA_RETENTION_CLEANUP:{now.date()}",{},datetime.combine(now.date(),time(h,m),now.tzinfo))
