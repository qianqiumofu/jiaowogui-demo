"""通知与模拟收件箱的 HTTP 入口（A 主责）。

收件箱读的是「本人作为收件人」的条目，范围由 user_id 直接确定、不依赖目录关系，
所以用 `require_own_resource` 而不是 `require`：辅导员的负责关系还没同步（pending），
但看自己的邮件预览不该被挡在门外。投递动作不在这里发生，入口只入队。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.clock import business_iso
from app.core.db import get_session
from app.modules.authorization.dependencies import require, require_own_resource
from app.modules.identity.schemas import SessionContext
from app.modules.notification import service
from app.modules.notification.schemas import DispatchRequest

router = APIRouter(tags=["notification"])

InboxDep = Annotated[SessionContext, Depends(require_own_resource("notification:read"))]
MarkReadDep = Annotated[SessionContext, Depends(require_own_resource("notification:mark_read"))]
DispatchDep = Annotated[SessionContext, Depends(require("notification:dispatch"))]
JobsDep = Annotated[SessionContext, Depends(require("notification_job:read"))]
SessionDep = Annotated[Session, Depends(get_session)]


def _notification(item) -> dict:
    return {
        "id": item.id,
        "template": item.template,
        "channel": item.channel,
        "subject": item.subject,
        "body": item.body,
        "status": item.status,
        "service_date": item.service_date.isoformat() if item.service_date else None,
        "recipient_email": item.recipient_email,
        "job_id": item.job_id,
        "created_at": business_iso(item.created_at),
        "read_at": business_iso(item.read_at) if item.read_at else None,
    }


def _job(job) -> dict:
    payload = dict(job.payload or {})
    return {
        "id": job.id,
        "job_type": job.job_type,
        "business_key": job.business_key,
        "status": job.status,
        "planned_at": business_iso(job.planned_at),
        "attempts": job.attempts,
        "last_error": job.last_error,
        "done_at": business_iso(job.done_at) if job.done_at else None,
        "template": payload.get("template"),
        "service_date": payload.get("service_date"),
        "recipient_user_ids": list(payload.get("recipient_user_ids") or []),
        "created_at": business_iso(job.created_at),
    }


@router.get("/notifications")
def read_inbox(guarded: InboxDep, db: SessionDep, unread_only: bool = False) -> dict:
    items = service.list_inbox(db, user_id=guarded.user_id, unread_only=unread_only)
    return {"items": [_notification(item) for item in items], "next_cursor": None}


@router.get("/notifications/{notification_id}")
def read_notification(
    notification_id: str, guarded: InboxDep, db: SessionDep
) -> dict:
    item = service.get_for_recipient(db, notification_id=notification_id, user_id=guarded.user_id)
    return _notification(item)


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str, request: Request, guarded: MarkReadDep, db: SessionDep
) -> dict:
    item = service.mark_read(
        db,
        request.app.state.clock,
        notification_id=notification_id,
        user_id=guarded.user_id,
    )
    return _notification(item)


@router.post("/notification-dispatch", status_code=202)
def dispatch_notifications(
    request: Request, guarded: DispatchDep, db: SessionDep, payload: DispatchRequest
) -> dict:
    job, deduped = service.dispatch(
        db,
        request.app.state.clock,
        actor=guarded,
        template=payload.template.value,
        service_date=payload.service_date,
        recipient_user_ids=payload.recipient_user_ids,
        student_ids=payload.student_ids,
        deliver_now=payload.deliver_now,
    )
    return {"jobs": [_job(job)], "deduped": deduped}


@router.get("/notification-jobs")
def read_jobs(guarded: JobsDep, db: SessionDep) -> dict:
    return {
        "items": [_job(job) for job in service.list_jobs(db)],
        "next_cursor": None,
    }
