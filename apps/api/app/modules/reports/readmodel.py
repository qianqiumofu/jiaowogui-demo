"""报告取数（A 主责）：日报、周报与通知正文共用的唯一读路径。

放在这里而不是各自写在 `notification` 里，是因为同一批事实会被两处消费——投递出去的正文
和辅导员当场打开的报告。两处如果分别取数、分别排序，数字迟早对不上，所以：

- 范围由调用方传入，本模块不判断「谁能看什么」（那是 `authorization` 的事）；
- 预约事实只经 `reservation.service` 的领域函数读取，不查对方表、不调对方 HTTP；
- 计数一律交给 `summary.py`，口径措辞与口径数字同源；
- 响应体的组装是纯函数，不连数据库也能验证。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.clock import Clock, business_iso, service_date_of
from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.models import Reservation
from app.modules.identity.adapters import mock_accounts
from app.modules.reports import summary
from app.modules.reservation import service as reservation_service

if TYPE_CHECKING:
    from app.modules.identity.schemas import SessionContext

# 口径措辞取自 `summary`，与计数同源；正文和报告因此不会各说一套。
UNCONFIRMED_NOTE = summary.UNCONFIRMED_NOTE
CANCELLED_NOTE = summary.CANCELLED_NOTE
SCOPE_NOTE_COUNSELOR = "只统计当前账号负责关系内的学生。"


def student_ids_of(context: SessionContext) -> list[str]:
    """辅导员范围里的学生主键；关系未同步时入口已被 403 挡住，这里只取已解析的部分。"""
    raw = context.scope.get("student_ids") or []
    return [str(item) for item in raw]


def scope_for(student_ids: list[str] | None) -> dict[str, object]:
    """`None`＝不按学生收窄（调用方已自行授权全量），空列表＝一个都不给看。

    这两种情况绝不能合并：辅导员还没同步到负责关系时拿到的是空列表，
    如果空列表也走全量分支，报告页就会把全校念给一个人听。
    """
    if student_ids is None:
        return {"scope": "ALL_AUTHORIZED", "resolved_by": "campus_grant"}
    return {"student_ids": list(student_ids), "resolved_by": "identity"}


def fetch(
    session: Session, clock: Clock, *, service_date: date | None = None, student_ids: list[str] | None = None
) -> list[Reservation]:
    items=reservation_service.list_reservations(session,clock,scope=scope_for(student_ids),service_date=service_date)
    from app.modules.directory.service import label_for
    for item in items:
        label=label_for(item.student_id)
        if label:
            item.directory_school_id,item.directory_display_name=label[0],label[1].split("（")[0]
    return items


def night_rows(
    session: Session, clock: Clock, *, service_date: date, student_ids: list[str] | None = None
) -> list[Reservation]:
    """当夜事实：整批读回后按业务夜筛，跨 06:00 的归属只在服务端判定。"""
    items = fetch(session, clock, student_ids=student_ids)
    return [res for res in items if res.service_date == service_date]


def week_window(end: date, *, nights: int | None = None) -> tuple[date, date]:
    count = nights if nights is not None else get_settings().weekly_report_nights
    return end - timedelta(days=count - 1), end


def range_rows(
    session: Session, clock: Clock, *, start: date, end: date, student_ids: list[str] | None = None
) -> list[Reservation]:
    items = fetch(session, clock, student_ids=student_ids)
    return [res for res in items if start <= res.service_date <= end]


def ordered(items: Iterable[Reservation]) -> list[Reservation]:
    """同一批事实的稳定顺序：先按计划返宿时刻，再按学生主键。"""
    return sorted(items, key=lambda res: (res.planned_return_at, res.student_id))


def labels(student_id: str) -> tuple[str, str]:
    person = mock_accounts.PEOPLE_BY_STUDENT_ID.get(student_id)
    if person is None:
        return "目录未同步", f"学生 {student_id}"
    return person.school_id, person.display_name.split("（")[0]


def facts(items: Iterable[Reservation]) -> list[summary.ReservationFact]:
    return [
        summary.ReservationFact(student_id=res.student_id, service_date=res.service_date, status=res.status)
        for res in items
    ]


def previous_night(moment: datetime) -> date:
    """辅导员默认看「前一晚」：业务日已经结束的最近一夜。"""
    return service_date_of(moment) - timedelta(days=1)


def resolve_service_date(value: date | None, *, now: datetime) -> date:
    """缺省看「前一晚」；晚于当前业务日的日期没有事实可读，直接拒。"""
    picked = value if value is not None else previous_night(now)
    latest = service_date_of(now)
    if picked > latest:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "只能查看当前业务夜及更早的记录。",
            {"service_date": picked.isoformat(), "latest": latest.isoformat()},
        )
    return picked


def caliber_notes() -> list[str]:
    return [CANCELLED_NOTE, UNCONFIRMED_NOTE]


def _row(res: Reservation) -> dict:
    school_id, display_name = reservation_labels(res)
    return {
        "student_id": res.student_id,
        "school_id": school_id,
        "display_name": display_name,
        "planned_return_at": business_iso(res.planned_return_at),
        "status": res.status,
    }


def daily_view(
    items: list[Reservation], *, service_date: date, now: datetime, scope_note: str = SCOPE_NOTE_COUNSELOR
) -> dict:
    start, end = reservation_service.night_bounds(service_date, now.tzinfo)
    rows = [_row(res) for res in ordered(items)]
    counted = facts(items)
    night = summary.summarize_night(counted, service_date=service_date)
    return {
        "template": "DAILY_REPORT",
        "service_date": service_date.isoformat(),
        "night_window": [business_iso(start), business_iso(end)],
        "generated_at": business_iso(now),
        "scope_note": scope_note,
        "totals": {
            "students": night.total,
            "nights": summary.distinct_nights(counted),
            "unconfirmed": night.unconfirmed,
        },
        "items": rows,
        "caliber_notes": caliber_notes(),
    }


def weekly_view(
    items: list[Reservation],
    *,
    start: date,
    end: date,
    now: datetime,
    scope_note: str = SCOPE_NOTE_COUNSELOR,
) -> dict:
    counted = facts(items)
    nights = summary.summarize_range(counted, start=start, end=end)
    return {
        "template": "WEEKLY_REPORT",
        "week_start": start.isoformat(),
        "service_date": end.isoformat(),
        "nights_covered": len(nights),
        "generated_at": business_iso(now),
        "scope_note": scope_note,
        "totals": {
            "students": summary.distinct_students(counted),
            "nights": summary.distinct_nights(counted),
            "unconfirmed": sum(night.unconfirmed for night in nights),
        },
        "nights": [
            {"service_date": night.service_date.isoformat(), "total": night.total, "unconfirmed": night.unconfirmed}
            for night in nights
        ],
        "caliber_notes": caliber_notes(),
    }


def statistic_facts(conn, *, start: date, end: date) -> list[dict]:
    """园区预约分母的领域出口；目录维度与正式返宿事实均经其负责人服务读取。"""
    from app.core.clock import build_clock
    from app.modules.directory.service import statistic_students
    from app.modules.returns.service import returned_keys
    returned = returned_keys(conn, start, end)
    dimensions = {}
    with Session(bind=conn) as session:
        rows = range_rows(session, build_clock(), start=start, end=end)
        out = []
        for res in rows:
            if res.status == "CANCELLED":
                continue
            if res.service_date not in dimensions:
                dimensions[res.service_date] = statistic_students(conn, res.service_date)
            meta = dimensions[res.service_date].get(res.student_id)
            if meta is not None:
                out.append({**meta, "service_date": res.service_date, "unconfirmed": (res.student_id, res.service_date) not in returned})
        return out


def reservation_labels(res):
    if hasattr(res,"directory_display_name"):
        return res.directory_school_id,res.directory_display_name
    return labels(res.student_id)
