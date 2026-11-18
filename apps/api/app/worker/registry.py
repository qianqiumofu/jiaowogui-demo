from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.db import get_engine

HANDLERS: dict[str, Callable[[dict], None]] = {}


def handler(job_type: str) -> Callable[[Callable[[dict], None]], Callable[[dict], None]]:
    """B 在此注册自有处理器（23:30 名单、导出、设备对账），不另起一套调度。"""

    def wrapper(func: Callable[[dict], None]) -> Callable[[dict], None]:
        HANDLERS[job_type] = func
        return func

    return wrapper


def claim_due_jobs(now: datetime, lease: timedelta) -> list[dict]:
    engine: Engine = get_engine()
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, job_type, business_key, payload
                    FROM background_jobs
                    WHERE status = 'PENDING' AND planned_at <= :now
                    ORDER BY planned_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 50
                    """
                ),
                {"now": now},
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
    return [dict(r) for r in rows]


def mark_succeeded(job_id: str, now: datetime) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE background_jobs SET status='DONE', done_at=:now WHERE id=:id"),
            {"now": now, "id": job_id},
        )


def mark_failed(job_id: str, error: str, now: datetime) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE background_jobs SET status='PENDING', last_error=:e, updated_at=:now WHERE id=:id"
            ),
            {"e": error[:500], "now": now, "id": job_id},
        )
