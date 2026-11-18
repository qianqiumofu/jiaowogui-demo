"""通知领域服务（A 主责）：入队、投递、模拟收件箱读取。

三条硬边界：
- 渠道由收件人账号来源决定（R18、R19）：统一身份 → 邮件预览，工号账号 → 站内待办；
  同一事件对同一收件人只落一个渠道，不给工号账号造邮件。
- 风险跟进提示的收件人只能是负责辅导员与当班宿管，园区被硬拒（R16）。
- 计划时刻一律由服务端时钟加配置算出，正文一律不含超时催办（R15、基线「统一日期与边界」）。

跨模块：预约事实只经 `reservation.service` 的领域函数读取，不查对方表、不调对方 HTTP。
任务只有 worker 进程消费，本模块的 HTTP 入口只入队不投递。
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock, service_date_of
from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.models import BackgroundJob, Notification, Reservation
from app.db.models.notification import NOTIFICATION_JOB_TYPE
from app.modules.identity import service as identity_service
from app.modules.identity.adapters import mock_accounts
from app.modules.identity.schemas import Person, Role, SessionContext
from app.modules.notification import templates
from app.modules.reservation import service as reservation_service
from app.modules.risk import rules as risk_rules

TEMPLATES = (
    "NIGHT_ROSTER",
    "DAILY_REPORT",
    "WEEKLY_REPORT",
    "RISK_ALERT",
)
# 模板与收件角色的对应关系来自 R12、R13、R16，不允许交叉投递。
RECIPIENT_ROLES: dict[str, set[Role]] = {
    "NIGHT_ROSTER": {Role.DORM_MANAGER},
    "DAILY_REPORT": {Role.COUNSELOR},
    "WEEKLY_REPORT": {Role.COUNSELOR},
    "RISK_ALERT": {Role.COUNSELOR, Role.DORM_MANAGER},
}
_INFLIGHT = ("PENDING", "RUNNING")
_MAX_RERUNS = 20


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def channel_for(person: Person) -> str:
    return "EMAIL" if person.email else "INBOX"


def resolve_recipient(user_id: str) -> Person:
    person = identity_service.person_by_user_id(user_id)
    if person is None:
        raise ApiError(
            404,
            "SUBJECT_NOT_FOUND",
            "收件人不存在、已停用或不在演示账号目录内。",
            {"recipient_user_id": user_id},
        )
    return person


def _assert_recipient(template: str, person: Person) -> None:
    allowed = RECIPIENT_ROLES[template]
    if template == "RISK_ALERT" and Role.CAMPUS in person.roles:
        raise ApiError(
            403,
            "NOTIFICATION_RECIPIENT_FORBIDDEN",
            "风险预警只投递负责辅导员与当班宿管，园区不作为收件人。",
            {"template": template, "recipient_user_id": person.user_id, "role": "CAMPUS", "rule": "R16"},
        )
    if not allowed & set(person.roles):
        raise ApiError(
            422,
            "NOTIFICATION_TEMPLATE_MISMATCH",
            "该模板不能投递给此收件人的角色。",
            {
                "template": template,
                "recipient_user_id": person.user_id,
                "role": sorted(role.value for role in person.roles),
                "allowed_roles": sorted(role.value for role in allowed),
            },
        )


def assert_recipients(template: str, recipient_user_ids: list[str]) -> None:
    """入队前先校验收件人资格，让「收件人不对」先于「数据不够」报出来。"""
    if template not in TEMPLATES:
        raise ApiError(422, "VALIDATION_FAILED", "未知的通知模板。", {"template": template})
    for user_id in sorted(set(recipient_user_ids)):
        _assert_recipient(template, resolve_recipient(user_id))


def _clock_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def planned_at(template: str, service_date: date, now: datetime) -> datetime:
    """任务计划时刻：名单在业务夜 23:30，日报次日早上，周报下一个周一，风险即时。"""
    settings = get_settings()
    tzinfo = now.tzinfo
    if template == "NIGHT_ROSTER":
        return datetime.combine(service_date, _clock_time(settings.roster_snapshot_at), tzinfo)
    if template == "DAILY_REPORT":
        day = service_date + timedelta(days=1)
        return datetime.combine(day, _clock_time(settings.daily_report_at), tzinfo)
    if template == "WEEKLY_REPORT":
        day = service_date + timedelta(days=1)
        weekday = settings.weekly_report_weekday
        day += timedelta(days=(weekday - day.weekday()) % 7)
        return datetime.combine(day, _clock_time(settings.weekly_report_at), tzinfo)
    return now


def _base_key(template: str, service_date: date, recipient_user_ids: list[str]) -> str:
    joined = ":".join(recipient_user_ids)
    base = f"{NOTIFICATION_JOB_TYPE}:{template}:{service_date.isoformat()}"
    if len(f"{base}:{joined}") <= 200:
        return f"{base}:{joined}"
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"{base}:{digest}"


def _slot_keys(base: str) -> Iterator[str]:
    """同一幂等键的重放槽位：进行中只有一条，已完成后再投递才产生新任务。"""
    yield base
    for index in range(1, _MAX_RERUNS):
        yield f"{base}:r{index}"


def _find_job(session: Session, business_key: str) -> BackgroundJob | None:
    return session.scalar(select(BackgroundJob).where(BackgroundJob.business_key == business_key))


def enqueue(
    session: Session,
    clock: Clock,
    *,
    template: str,
    service_date: date,
    recipient_user_ids: list[str],
    student_ids: list[str] | None = None,
    requested_by: str | None = None,
    demo_manual: bool = False,
    deliver_now: bool = False,
) -> tuple[BackgroundJob, bool]:
    """按幂等键入队；已有进行中的同一任务时返回原任务，不重复投递。

    `reports`、`duty` 与 B 的模块都经这里投递，不自行写 `background_jobs`。
    """
    if template not in TEMPLATES:
        raise ApiError(422, "VALIDATION_FAILED", "未知的通知模板。", {"template": template})
    recipients = sorted(set(recipient_user_ids))
    if not recipients:
        raise ApiError(422, "VALIDATION_FAILED", "收件人不能为空。", {"field": "recipient_user_ids"})
    assert_recipients(template, recipients)

    base = _base_key(template, service_date, recipients)
    free_key: str | None = None
    for key in _slot_keys(base):
        existing = _find_job(session, key)
        if existing is None:
            free_key = key
            break
        if existing.status in _INFLIGHT:
            return existing, True
    if free_key is None:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            f"同一模板与业务夜的重复投递已达上限（{_MAX_RERUNS} 次）。",
            {"business_key": base},
        )

    now = clock.now()
    payload = {
        "template": template,
        "service_date": service_date.isoformat(),
        "recipient_user_ids": recipients,
        "student_ids": sorted(set(student_ids or [])),
        "requested_by": requested_by,
        "demo_manual": demo_manual,
    }
    job = BackgroundJob(
        id=new_id("job"),
        job_type=NOTIFICATION_JOB_TYPE,
        business_key=free_key,
        payload=payload,
        planned_at=now if deliver_now else planned_at(template, service_date, now),
        status="PENDING",
        attempts=0,
    )
    try:
        session.add(job)
        session.commit()
    except IntegrityError:
        # 并发入队：唯一键只放行一条，另一条按去重返回。
        session.rollback()
        raced = _find_job(session, free_key)
        if raced is None:
            raise
        return raced, True
    return job, False


def _rows_from(items: list[Reservation]) -> list[templates.ReservationRow]:
    rows: list[templates.ReservationRow] = []
    for res in items:
        school_id, display_name = _labels(res.student_id)
        rows.append(
            templates.ReservationRow(
                student_id=res.student_id,
                school_id=school_id,
                display_name=display_name,
                planned_return_at=res.planned_return_at,
                status=res.status,
            )
        )
    return sorted(rows, key=lambda row: (row.planned_return_at, row.student_id))


def _fetch(
    session: Session, clock: Clock, *, service_date: date | None, student_ids: list[str] | None
) -> list[Reservation]:
    if student_ids:
        scope: dict[str, object] = {"student_ids": list(student_ids), "resolved_by": "identity"}
    else:
        scope = {"scope": "ALL_AUTHORIZED", "resolved_by": "campus_grant"}
    return reservation_service.list_reservations(session, clock, scope=scope, service_date=service_date)


def _night_rows(
    session: Session, clock: Clock, *, service_date: date, student_ids: list[str] | None
) -> list[Reservation]:
    items = [
        res
        for res in _fetch(session, clock, service_date=None, student_ids=student_ids)
        if res.service_date == service_date
    ]
    return items


def _week_rows(
    session: Session, clock: Clock, *, week_start: date, service_date: date, student_ids: list[str] | None
) -> list[Reservation]:
    items = [
        res
        for res in _fetch(session, clock, service_date=None, student_ids=student_ids)
        if week_start <= res.service_date <= service_date
    ]
    return items


def _night_counts(items: list[Reservation], *, week_start: date, service_date: date) -> list[templates.NightCount]:
    buckets: dict[date, list[Reservation]] = {}
    for res in items:
        buckets.setdefault(res.service_date, []).append(res)
    counts: list[templates.NightCount] = []
    for offset in range((service_date - week_start).days + 1):
        day = week_start + timedelta(days=offset)
        rows = [res for res in buckets.get(day, []) if res.status != "CANCELLED"]
        unconfirmed = [res for res in rows if res.status in ("ACTIVE", "CLOSED")]
        counts.append(
            templates.NightCount(
                service_date=day, total=len(rows), unconfirmed=len(unconfirmed)
            )
        )
    return counts


def _labels(student_id: str) -> tuple[str, str]:
    person = mock_accounts.PEOPLE_BY_STUDENT_ID.get(student_id)
    if person is None:
        return "目录未同步", f"学生 {student_id}"
    return person.school_id, person.display_name.split("（")[0]


def risk_facts(
    session: Session, clock: Clock, *, service_date: date, student_ids: list[str] | None
) -> list[templates.RiskFacts]:
    """按配置阈值挑出该业务夜应发跟进提示的学生。

    阈值、窗口与连续性口径统一由 A 的 `risk.rules` 计算（唯一计算处），本函数只取数与
    组装正文事实。口径只有「预约晚归的次数与连续性」：实际是否晚归要 B 的返宿记录，
    未确认返宿不作为触发条件（R15）。
    """
    rule_set = risk_rules.current_rule_set()
    window_start = service_date - timedelta(days=rule_set.window_nights - 1)
    items = _week_rows(
        session, clock, week_start=window_start, service_date=service_date, student_ids=student_ids
    )
    by_student: dict[str, list[Reservation]] = {}
    for res in items:
        if res.status != "CANCELLED":
            by_student.setdefault(res.student_id, []).append(res)

    facts: list[templates.RiskFacts] = []
    for student_id, rows in by_student.items():
        evaluation = risk_rules.evaluate(
            (res.service_date for res in rows), tonight=service_date, rules=rule_set
        )
        if not evaluation.crossed:
            continue
        latest = max(rows, key=lambda res: (res.service_date, res.planned_return_at))
        school_id, display_name = _labels(student_id)
        facts.append(
            templates.RiskFacts(
                row=templates.ReservationRow(
                    student_id=student_id,
                    school_id=school_id,
                    display_name=display_name,
                    planned_return_at=latest.planned_return_at,
                    status=latest.status,
                ),
                window_nights=evaluation.window_nights,
                times=evaluation.times,
                consecutive=evaluation.consecutive_nights,
                nights=list(evaluation.nights),
            )
        )
    return sorted(facts, key=lambda fact: fact.row.student_id)


def assert_risk_triggers(
    session: Session, clock: Clock, *, service_date: date, student_ids: list[str] | None
) -> None:
    if risk_facts(session, clock, service_date=service_date, student_ids=student_ids):
        return
    settings = get_settings()
    raise ApiError(
        422,
        "VALIDATION_FAILED",
        "所选学生在该业务夜未达演示配置的提示条件，不生成跟进提示。",
        {
            "service_date": service_date.isoformat(),
            "threshold": {
                "window_nights": settings.risk_window_nights,
                "times": settings.risk_times_threshold,
                "consecutive": settings.risk_consecutive_threshold,
            },
        },
    )


def dispatch(
    session: Session,
    clock: Clock,
    *,
    actor: SessionContext,
    template: str,
    service_date: date | None,
    recipient_user_ids: list[str],
    student_ids: list[str] | None = None,
    deliver_now: bool = False,
) -> tuple[BackgroundJob, bool]:
    """园区的演示投递入口：校验边界后入队，投递动作留给 worker。"""
    moment = clock.now()
    night = service_date or service_date_of(moment)
    assert_recipients(template, recipient_user_ids)
    if template == "RISK_ALERT":
        assert_risk_triggers(session, clock, service_date=night, student_ids=student_ids)
    return enqueue(
        session,
        clock,
        template=template,
        service_date=night,
        recipient_user_ids=recipient_user_ids,
        student_ids=student_ids,
        requested_by=actor.user_id,
        demo_manual=True,
        deliver_now=deliver_now,
    )


def _insert(
    session: Session,
    *,
    business_key: str,
    job_id: str | None,
    template: str,
    person: Person,
    subject: str,
    body: str,
    service_date: date,
) -> int:
    duplicate = session.scalar(
        select(Notification).where(
            Notification.recipient_user_id == person.user_id,
            Notification.business_key == business_key,
        )
    )
    if duplicate is not None:
        return 0
    session.add(
        Notification(
            id=new_id("ntf"),
            business_key=business_key,
            job_id=job_id,
            template=template,
            channel=channel_for(person),
            recipient_user_id=person.user_id,
            recipient_email=person.email,
            subject=subject,
            body=body,
            service_date=service_date,
            status="SENT",
        )
    )
    return 1


def _render_input(
    session: Session,
    clock: Clock,
    *,
    template: str,
    service_date: date,
    student_ids: list[str] | None,
    demo_manual: bool,
    person: Person,
) -> list[tuple[str, templates.RenderInput]]:
    """返回 [(幂等键后缀, 渲染输入)]；风险提示按学生拆分，其余一条。"""
    if template == "NIGHT_ROSTER":
        items = [res for res in _night_rows(session, clock, service_date=service_date, student_ids=student_ids) if res.status != "CANCELLED"]
        return [
            (
                "",
                templates.RenderInput(
                    template=template,
                    person=person,
                    service_date=service_date,
                    rows=_rows_from(items),
                    demo_manual=demo_manual,
                ),
            )
        ]
    if template == "DAILY_REPORT":
        return [
            (
                "",
                templates.RenderInput(
                    template=template,
                    person=person,
                    service_date=service_date,
                    rows=_rows_from(
                        _night_rows(session, clock, service_date=service_date, student_ids=student_ids)
                    ),
                    demo_manual=demo_manual,
                ),
            )
        ]
    if template == "WEEKLY_REPORT":
        week_start = service_date - timedelta(days=get_settings().weekly_report_nights - 1)
        items = _week_rows(
            session,
            clock,
            week_start=week_start,
            service_date=service_date,
            student_ids=student_ids,
        )
        return [
            (
                "",
                templates.RenderInput(
                    template=template,
                    person=person,
                    service_date=service_date,
                    nights=_night_counts(items, week_start=week_start, service_date=service_date),
                    week_start=week_start,
                    demo_manual=demo_manual,
                ),
            )
        ]
    facts = risk_facts(
        session, clock, service_date=service_date, student_ids=student_ids
    )
    return [
        (
            f":{fact.row.student_id}",
            templates.RenderInput(
                template=template,
                person=person,
                service_date=service_date,
                risk=fact,
                demo_manual=demo_manual,
            ),
        )
        for fact in facts
    ]


def deliver(
    session: Session, clock: Clock, *, job_id: str | None, business_key: str, payload: dict
) -> int:
    """worker 消费任务：在投递时刻重新取数，保证名单反映最新改期与返宿（R12）。"""
    template = str(payload.get("template", ""))
    if template not in TEMPLATES:
        raise ApiError(422, "VALIDATION_FAILED", "任务负载里的通知模板未知。", {"template": template})
    service_date = date.fromisoformat(str(payload["service_date"]))
    student_ids = [str(item) for item in payload.get("student_ids") or []] or None
    demo_manual = bool(payload.get("demo_manual"))
    created = 0
    for user_id in payload.get("recipient_user_ids") or []:
        person = identity_service.person_by_user_id(str(user_id))
        if person is None:
            continue  # 收件人已停用：跳过而不是让任务无限重试
        _assert_recipient(template, person)
        for suffix, item in _render_input(
            session,
            clock,
            template=template,
            service_date=service_date,
            student_ids=student_ids,
            demo_manual=demo_manual,
            person=person,
        ):
            subject, body = templates.render(item)
            created += _insert(
                session,
                business_key=f"{business_key}:{person.user_id}{suffix}",
                job_id=job_id,
                template=template,
                person=person,
                subject=subject,
                body=body,
                service_date=service_date,
            )
    session.commit()
    return created


def list_inbox(
    session: Session, *, user_id: str, unread_only: bool
) -> list[Notification]:
    query = select(Notification).where(Notification.recipient_user_id == user_id)
    if unread_only:
        query = query.where(Notification.status == "SENT")
    return list(session.scalars(query.order_by(Notification.created_at.desc(), Notification.id)))


def get_for_recipient(session: Session, *, notification_id: str, user_id: str) -> Notification:
    item = session.get(Notification, notification_id)
    if item is None or item.recipient_user_id != user_id:
        raise ApiError(
            404,
            "NOTIFICATION_NOT_FOUND",
            "通知不存在或不属于当前收件人。",
            {"notification_id": notification_id},
        )
    return item


def mark_read(session: Session, clock: Clock, *, notification_id: str, user_id: str) -> Notification:
    item = get_for_recipient(session, notification_id=notification_id, user_id=user_id)
    if item.status != "READ":
        item.status = "READ"
        item.read_at = clock.now()
        session.commit()
    return item


def list_jobs(session: Session) -> list[BackgroundJob]:
    return list(
        session.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.job_type == NOTIFICATION_JOB_TYPE)
            .order_by(BackgroundJob.planned_at.desc(), BackgroundJob.id)
        )
    )
