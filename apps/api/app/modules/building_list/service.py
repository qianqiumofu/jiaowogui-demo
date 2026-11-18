"""当晚名单读模型（B 主责）：目录快照 ⨷ A 的预约 ⨷ 24:00 汇总的差异。

- 24:00（业务夜 D 的 D+1 00:00）向宿管汇总并推送人数，该时刻只关闭 D 这一夜的首次申请（R12）；
  次夜（D+1）的申请不受影响，判定一律按预约所属业务夜走。
- 汇总之后名单只接受改期与撤销，实时进列表并标异动；新增只可能是越权异常，标 `ADDED_AFTER_SUMMARY`。
- 名单只包含所查业务夜当天的预约，越夜数据不进列表；06:00 一到自动切次夜（R04、R12）。
- 名单读取 B 的正式返宿记录来显示门禁通行情况（已通行 X / 共 N 人），通行只展示不推送。
- 名单不含联系方式；联系方式由 `contact:read_duty` 单独取（docs/08 字段级权限）。
- 只允许查询当前有效值班范围内的楼栋（R11）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.clock import is_summary_passed, service_date_of, summary_moment
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import out_of_scope
from app.modules.building_list import notify, source
from app.modules.directory import service as directory
from app.modules.returns import service as returns

SUMMARY_KEY = "DORM_TONIGHT_SNAPSHOT"

_LOAD_SNAPSHOT_SQL = text(
    """
    SELECT payload, generated_at
    FROM building_list_snapshots
    WHERE building_id = :building_id AND service_date = :service_date
    """
)

_UPSERT_SNAPSHOT_SQL = text(
    """
    INSERT INTO building_list_snapshots (snapshot_id, building_id, service_date, generated_at, payload)
    VALUES (:snapshot_id, :building_id, :service_date, :generated_at, CAST(:payload AS JSONB))
    ON CONFLICT (building_id, service_date) DO NOTHING
    """
)


def ensure_building_in_scope(scope: dict, building_id: str) -> list[str]:
    allowed = [str(item) for item in scope.get("building_ids") or []]
    if building_id not in allowed:
        raise out_of_scope("building", building_id, allowed)
    return allowed


def _change_flag(previous: dict | None, current: dict) -> str | None:
    """异动标记只在 24:00 汇总之后才有基准；汇总前返回 None。

    24:00 后首次申请已被 A 拒绝，因此 `previous is None` 属于越权/跨夜异常，仍标出来便于对账。
    """
    if previous is None:
        return "ADDED_AFTER_SUMMARY"
    if current["reservation_status"] == "CANCELLED" and previous["reservation_status"] != "CANCELLED":
        return "CANCELLED"
    if current["planned_return_at"] != previous["planned_return_at"]:
        return "RESCHEDULED"
    return None


def build_items(
    residents: list[dict],
    reservations: list[dict],
    summary_items: list[dict] | None,
    service_date: date,
    returned: Mapping[str, dict],
) -> list[dict]:
    """把预约流水折成阿姨要的一行一条；住宿与学院按汇总时快照取值（基线统计口径）。

    名单只允许出现 `service_date` 当夜那一条业务夜的预约（R12）：A 的源按夜取数，
    这里再校验一遍，越夜的脏数据直接丢弃而不是显示给阿姨，免得汇总口径被带偏。
    返宿与否只认 B 的正式记录（R10）：`reservation_status == FULFILLED` 不算已返宿，
    领码、核验、申请本身都不产生返宿事实。
    """
    by_student = {resident["student_id"]: resident for resident in residents}
    baseline = {item["student_id"]: item for item in summary_items} if summary_items is not None else None
    night = service_date.isoformat()

    items: list[dict] = []
    for reservation in reservations:
        student_id = reservation["student_id"]
        if str(reservation.get("service_date") or "")[:10] != night:
            continue
        resident = by_student.get(student_id)
        if resident is None:
            # 住宿归属与预约楼栋不一致：交给目录同步排查，不在本楼栋名单里编造寝室。
            continue
        current = {
            "student_id": student_id,
            "school_id": resident["school_id"],
            "display_name": resident["display_name"],
            "room_no": resident["room_no"],
            "college_name": resident["college_name"],
            "grade": resident["grade"],
            "planned_return_at": reservation["planned_return_at"],
            "reservation_status": reservation["status"],
            "reservation_version": reservation["version"],
            "updated_at": reservation["updated_at"],
        }
        current.update(_passage(returned.get(student_id)))
        current["change_flag"] = (
            None if baseline is None else _change_flag(baseline.get(student_id), current)
        )
        items.append(current)

    _append_manual_additions(items, by_student, returned, baseline)

    items.sort(key=lambda item: (item["room_no"], item["school_id"]))
    return items


def _append_manual_additions(
    items: list[dict],
    by_student: dict,
    returned: Mapping[str, dict],
    baseline: dict | None,
) -> None:
    """把没有预约、却已人工补录返宿的学生补成名单里的一行（需求：补录进当夜汇总名单）。

    晚归时间取该条补录记录的返宿时刻，也就是宿管的录入时刻；已在预约行里出现的学生不重复补，
    免得同一学生既有预约行又冒出一条补录行。`ADDED_AFTER_SUMMARY` 标记它落在 24:00 汇总基准之外。
    """
    listed = {item["student_id"] for item in items}
    for student_id, record in returned.items():
        if student_id in listed or record["source"] != returns.SOURCE_MANUAL:
            continue
        resident = by_student.get(student_id)
        if resident is None:
            continue
        row = {
            "student_id": student_id,
            "school_id": resident["school_id"],
            "display_name": resident["display_name"],
            "room_no": resident["room_no"],
            "college_name": resident["college_name"],
            "grade": resident["grade"],
            # 补录者没有预约，晚归时间即录入时刻（返宿发生时间）。
            "planned_return_at": record["occurred_at"],
            "reservation_status": "NONE",
            "reservation_version": None,
            "updated_at": None,
        }
        row.update(_passage(record))
        row["change_flag"] = None if baseline is None else "ADDED_AFTER_SUMMARY"
        items.append(row)


def _passage(record: dict | None) -> dict:
    """通行状态由正式返宿记录派生：没有记录就是未通行，不靠预约状态猜。"""
    if record is None:
        return {
            "return_status": "PENDING",
            "entered_at": None,
            "gate_id": None,
            "return_source": None,
        }
    return {
        "return_status": "ENTERED" if record["source"] == returns.SOURCE_QR else "MANUAL_ENTERED",
        "entered_at": record["occurred_at"],
        "gate_id": record["gate_id"],
        "return_source": record["source"],
    }


def load_summary_items(building_id: str, service_date: date) -> tuple[list[dict] | None, str | None]:
    with get_engine().connect() as conn:
        row = conn.execute(
            _LOAD_SNAPSHOT_SQL, {"building_id": building_id, "service_date": service_date}
        ).mappings().first()
    if row is None:
        return None, None
    payload = row["payload"] or {}
    generated = row["generated_at"]
    # 驱动按 UTC 回传，业务时间一律换算回业务时区再出接口。
    if generated is not None:
        generated = generated.astimezone(ZoneInfo(get_settings().business_timezone))
    return payload.get("items", []), generated.isoformat() if generated else None


def tonight(building_id: str, at: datetime) -> dict:
    """阿姨端的「今晚名单」：严格只覆盖 `at` 所属的那一夜。

    06:00 一到，`service_date_of` 自动把请求翻到次夜，前一夜的通行情况不在本页
    留存（去返宿记录页查历史）。通行只是读，不产生任何推送。
    """
    service_date = service_date_of(at)
    residents = directory.list_building_residents(building_id, at)
    reservations = source.reservations_for_building(building_id, service_date)
    summary_items, summary_generated_at = load_summary_items(building_id, service_date)
    items = build_items(residents, reservations, summary_items, service_date,
                        returns.records_by_student(building_id, service_date))
    return {
        "building_id": building_id,
        "service_date": service_date.isoformat(),
        "summary_generated_at": summary_generated_at,
        "counters": {
            "total": len(items),
            "entered": sum(1 for item in items if item["return_status"] != "PENDING"),
        },
        "items": items,
        "next_cursor": None,
    }


def write_snapshot(
    building_id: str, service_day: date, generated_at: datetime, items: list[dict]
) -> None:
    """24:00 汇总落库；已存在则不覆盖，保证同一晚只有一份基准（幂等）。"""
    payload = {
        "items": [
            {
                "student_id": item["student_id"],
                "planned_return_at": item["planned_return_at"],
                "reservation_status": item["reservation_status"],
                "reservation_version": item["reservation_version"],
            }
            for item in items
        ]
    }
    with get_engine().begin() as conn:
        conn.execute(
            _UPSERT_SNAPSHOT_SQL,
            {
                "snapshot_id": f"snap_{uuid.uuid4().hex[:20]}",
                "building_id": building_id,
                "service_date": service_day,
                "generated_at": generated_at,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
        )


def snapshot_is_due(at: datetime, service_day: date | None = None) -> bool:
    """业务夜 D 的汇总在 D+1 00:00 到期；演示时钟推进到这里即可复现。"""
    return is_summary_passed(at, service_day)


def run_snapshot(building_id: str, service_day: date) -> int:
    """worker 任务体：以目录当晚住宿为基准冻结名单，之后的改期与撤销只标异动不回写。

    基准时刻取该业务夜的汇总时刻，因此与 worker 实际运行的墙钟无关，可重放。
    落库后主动给当班阿姨推一条「已汇总共 N 人」（需求 ②），推送失败让任务重试，
    快照写入本身幂等，重试不会产生第二份基准。
    """
    anchor = summary_moment(service_day, ZoneInfo(get_settings().business_timezone))
    residents = directory.list_building_residents(building_id, anchor)
    reservations = source.reservations_for_building(building_id, service_day)
    # 基准取 00:00，门禁刚开，当夜不可能已有通行，因此传空记录而不是查库。
    items = build_items(residents, reservations, None, service_day, {})
    write_snapshot(building_id, service_day, anchor, items)
    notify.push_summary(building_id, service_day, items, anchor)
    return len(items)


__all__ = [
    "SUMMARY_KEY",
    "build_items",
    "ensure_building_in_scope",
    "load_summary_items",
    "run_snapshot",
    "snapshot_is_due",
    "tonight",
    "write_snapshot",
]
