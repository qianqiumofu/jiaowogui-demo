"""风险领域服务（A 主责）：从预约事实派生规则结果。

跨模块边界：预约事实只经 `reservation.service` 的领域函数读取，不查对方表、不调对方 HTTP。
本模块当前是纯派生：不写通知任务（R15 的超时与未确认不产生任何提醒）、不落风险事件表。
风险事件的持久化与跟进要按负责辅导员与当班宿管派生收件人，等 B 的目录与值班关系落地后
另开一项（见 `双人协作分工.md` 的「A 侧下一项」）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import Clock, service_date_of
from app.modules.reservation import service as reservation_service
from app.modules.risk import rules, templates


def late_nights(session: Session, clock: Clock, *, student_id: str) -> list[date]:
    """该生全部非取消预约的业务夜；取消不计晚归夜数，窗口裁剪交给规则引擎。"""
    items = reservation_service.list_reservations(
        session,
        clock,
        scope={"student_id": student_id, "resolved_by": "identity"},
        service_date=None,
    )
    return [res.service_date for res in items if res.status != "CANCELLED"]


def evaluate_student(
    session: Session, clock: Clock, *, student_id: str, tonight: date | None = None
) -> rules.Evaluation:
    return rules.evaluate(
        late_nights(session, clock, student_id=student_id),
        tonight=tonight or service_date_of(clock.now()),
        rules=rules.current_rule_set(),
    )


def notice_for_create(
    session: Session, clock: Clock, *, student_id: str, service_date: date
) -> dict[str, Any] | None:
    """本夜预约使窗口内口径越界时返回弹窗事实，否则 None。

    判定不含「学生是否已返宿」，所以未确认返宿永远不会变成弹窗或催办（R15）。
    """
    evaluation = evaluate_student(
        session, clock, student_id=student_id, tonight=service_date
    )
    if not evaluation.first_crossing:
        return None
    title, message = templates.render_notice(evaluation)
    return {
        "rule_version": evaluation.rule_version,
        "window_nights": evaluation.window_nights,
        "nights": [day.isoformat() for day in evaluation.nights],
        "times": evaluation.times,
        "consecutive_nights": evaluation.consecutive_nights,
        "triggered_by": evaluation.crossed_by,
        "title": title,
        "message": message,
    }
