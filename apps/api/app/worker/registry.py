from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.core.config import get_settings

HANDLERS: dict[str, Callable[[dict], None]] = {}


def handler(job_type: str) -> Callable[[Callable[[dict], None]], Callable[[dict], None]]:
    """B 在此注册自有处理器（24:00 名单、导出、设备对账），不另起一套调度。"""

    def wrapper(func: Callable[[dict], None]) -> Callable[[dict], None]:
        HANDLERS[job_type] = func
        return func

    return wrapper


def claim_due_jobs(now: datetime, lease: timedelta) -> list[dict]:
    engine: Engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE background_jobs SET status='FAILED',lease_until=NULL,last_error='LEASE_RETRY_EXHAUSTED',updated_at=:now WHERE status='RUNNING' AND lease_until<=:now AND attempts>=:maximum"),{'now':now,'maximum':get_settings().worker_max_attempts})
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, job_type, business_key, payload, attempts
                    FROM background_jobs
                    WHERE (status = 'PENDING' AND planned_at <= :now) OR (status='RUNNING' AND lease_until <= :now)
                    ORDER BY planned_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT :batch
                    """
                ),
                {"now": now,"batch":get_settings().worker_batch_size},
            )
            .mappings()
            .all()
        )
        for row in rows:
            conn.execute(
                text(
                    """
                    UPDATE background_jobs
                    SET status = 'RUNNING', lease_until = :until, attempts = attempts + 1
                    WHERE id = :id
                    """
                ),
                {"until": now + lease, "id": row["id"]},
            )
    return [{**dict(r),"attempts":r["attempts"]+1} for r in rows]


def mark_succeeded(job_id: str, now: datetime, attempts: int | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE background_jobs SET status='DONE',done_at=:now,lease_until=NULL,last_error=NULL WHERE id=:id AND status='RUNNING' AND attempts=COALESCE(CAST(:attempt AS INTEGER),attempts)"),{"now":now,"id":job_id,"attempt":attempts})


def mark_failed(job_id: str, error: str, now: datetime, attempts: int | None = None) -> None:
    settings=get_settings()
    with get_engine().begin() as conn:
        row=conn.execute(text("SELECT attempts FROM background_jobs WHERE id=:id"),{"id":job_id}).first()
        if row is None:return
        count=int(row[0]);delay=min(settings.worker_retry_max_seconds,settings.worker_retry_base_seconds*2**max(count-1,0))
        conn.execute(text("UPDATE background_jobs SET status=:status,last_error=:e,updated_at=:now,planned_at=:next,lease_until=NULL WHERE id=:id AND status='RUNNING' AND attempts=COALESCE(CAST(:attempt AS INTEGER),attempts)"),
            {"status":"FAILED" if count>=settings.worker_max_attempts else "PENDING","e":error[:500],"now":now,"next":now+timedelta(seconds=delay),"id":job_id,"attempt":attempts})


@handler("DORM_TONIGHT_SNAPSHOT")
def dorm_tonight_snapshot(job: dict) -> None:
    """24:00 楼栋名单汇总（B）。经 A 的预约领域服务读取，推送由共享通知服务处理。"""
    from app.modules.building_list import service as building_list

    payload = job["payload"] or {}
    building_list.run_snapshot(
        str(payload["building_id"]), date.fromisoformat(str(payload["service_date"]))
    )


@handler("EXPORT_BUILD")
def export_build(job: dict) -> None:
    """园区受控导出（B）：把统计口径渲染成 CSV 落回 `export_jobs`，口径错误由服务落 FAILED。"""
    from app.core.clock import build_clock
    from app.modules.exports import service as exports

    payload = job["payload"] or {}
    exports.build(str(payload["export_id"]), build_clock().now())


@handler("COUNSELOR_DAILY_REPORT")
@handler("COUNSELOR_WEEKLY_REPORT")
def periodic_report(job):
    from sqlalchemy.orm import Session
    from app.core.clock import build_clock
    from app.modules.reports.subscriptions import get
    from app.modules.notification.service import deliver
    from app.modules.identity.service import person_by_user_id
    from app.modules.identity.schemas import Role
    payload=job["payload"];template=payload["template"]
    flag="daily" if template=="DAILY_REPORT" else "weekly"
    eligible=[]
    for user in payload["recipient_user_ids"]:
        person=person_by_user_id(user)
        if person and set(person.roles)&{Role.COUNSELOR,Role.IDEOLOGY} and get(user)[flag]:eligible.append(user)
    if eligible:
        with Session(get_engine()) as db:
            deliver(db,build_clock(),job_id=job["id"],business_key=job["business_key"],payload={**payload,"recipient_user_ids":eligible})


@handler("RISK_PERIODIC_EVALUATION")
def periodic_risk(job):
    from sqlalchemy.orm import Session
    from app.core.clock import build_clock
    from app.modules.risk.events import evaluate_all
    with Session(get_engine()) as db:
        evaluate_all(db,build_clock(),date.fromisoformat(job["payload"]["service_date"]))


@handler("DATA_RETENTION_CLEANUP")
def retention_cleanup(job):
    from app.core.clock import build_clock
    from app.modules.exports.service import cleanup_expired
    from app.modules.identity.persistence import cleanup_expired_sessions
    from app.modules.access.service import cleanup_expired_passes
    now=build_clock().now()
    cleanup_expired(now);cleanup_expired_sessions(now);cleanup_expired_passes(now)


@handler("DEVICE_RECONCILE")
def device_reconcile(job):
    from app.core.clock import build_clock
    from app.modules.access.receipts import reconcile
    reconcile(job["payload"]["attempt_id"],build_clock().now())
