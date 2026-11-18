"""宿管推送装配（B 主责）：预约异动与 24:00 汇总完成时给当班阿姨的消息。

- 收件人只取该楼栋此刻的当班人员（R11）；园区不接收风险与名单推送（R16）。
- 消息允许携带联系方式：推送通道本身按当班范围解析收件人，名单接口仍不返回该字段（docs/08 字段级权限）。
- 发送走 A 的 `notification.enqueue` 接缝，B 不自己起调度、不直接发信。
"""

from __future__ import annotations

from datetime import date, datetime

from app.core.errors import not_implemented
from app.modules.directory import service as directory

CAPABILITY = "notification.enqueue"
CHANGE_KINDS = ("APPROVED", "RESCHEDULED", "CANCELLED")

_TEMPLATES = {
    "APPROVED": "dorm.reservation.approved",
    "RESCHEDULED": "dorm.reservation.rescheduled",
    "CANCELLED": "dorm.reservation.cancelled",
}
SUMMARY_TEMPLATE = "dorm.list.summary"


def _label(change_kind: str) -> str:
    return {"APPROVED": "晚归预约", "RESCHEDULED": "改期", "CANCELLED": "撤销"}[change_kind]


def compose(event: dict, at: datetime) -> dict:
    """把 A 的预约事件折成阿姨可读的一条消息；住宿与学院取业务夜快照。"""
    change_kind = event["change_kind"]
    if change_kind not in CHANGE_KINDS:
        raise ValueError(f"未知的预约异动类型：{change_kind}")
    contact = directory.get_contact(event["student_id"], at)
    if contact is None:
        # 归属缺失时不编造寝室，交给目录同步排查；消息仍按学号发出，便于阿姨核对。
        contact = {
            "school_id": event.get("school_id") or event["student_id"],
            "display_name": None,
            "building_id": event["building_id"],
            "room_no": "归属待同步",
            "phone": None,
        }
    summary = f"{contact['room_no']} {contact['display_name'] or ''}（{contact['school_id']}）"
    summary = " ".join(summary.split())
    if change_kind == "CANCELLED":
        body = f"【{_label(change_kind)}】{summary}已取消今晚晚归预约。"
    elif change_kind == "RESCHEDULED":
        body = f"【{_label(change_kind)}】{summary}晚归时间改为 {event['planned_return_at']}。"
    else:
        college = f"，{contact['college_name']}" if contact.get("college_name") else ""
        phone = contact.get("phone") or "未登记"
        body = (
            f"【{_label(change_kind)}】{summary}{college}计划 "
            f"{event['planned_return_at']} 返宿，联系 {phone}。"
        )
    building_id = contact["building_id"]
    student_id = event["student_id"]
    version = event.get("reservation_version", 0)
    return {
        "template": _TEMPLATES[change_kind],
        "title": f"【{_label(change_kind)}】{building_id}",
        "body": body,
        "student_id": student_id,
        "school_id": contact["school_id"],
        "building_id": building_id,
        "room_no": contact["room_no"],
        "phone": contact.get("phone"),
        "planned_return_at": event.get("planned_return_at"),
        "change_kind": change_kind,
        "dedup_key": f"dorm:{building_id}:{student_id}:{change_kind}:{version}",
    }


def compose_summary(
    building_id: str, service_day: date, items: list[dict], at: datetime
) -> dict:
    """24:00 汇总完成后给阿姨的那一条；只报当夜人数，明细走名单接口。"""
    count = len(items)
    night = service_day.isoformat()
    return {
        "template": SUMMARY_TEMPLATE,
        "title": f"【已汇总】{building_id}",
        "body": (
            f"【已汇总】{night} 当晚晚归申请共 {count} 人，名单已同步；"
            "该时刻起只接受改期与撤销，异动实时更新。"
        ),
        "building_id": building_id,
        "service_date": night,
        "student_count": count,
        "dedup_key": f"dorm:{building_id}:{night}:SUMMARY",
    }


def recipients(building_id: str, at: datetime) -> list[str]:
    return directory.get_duty_staff(building_id, at)


def _dispatch(message: dict, at: datetime) -> dict:
    """解析当班收件人后交给 A 的发送队列；无人在班时返回空收件人，不降级为群发。"""
    recipient_ids = recipients(message["building_id"], at)
    try:
        from app.modules.notification.service import enqueue
    except ImportError as exc:
        raise not_implemented("M2", CAPABILITY) from exc
    enqueue(
        message["template"],
        recipient_ids,
        {k: v for k, v in message.items() if k != "template"},
        message["dedup_key"],
    )
    return {"recipients": recipient_ids, "message": message}


def push(event: dict, at: datetime) -> dict:
    return _dispatch(compose(event, at), at)


def push_summary(
    building_id: str, service_day: date, items: list[dict], at: datetime
) -> dict:
    return _dispatch(compose_summary(building_id, service_day, items, at), at)
