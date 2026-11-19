"""名单的预约数据源接缝：只调用 A 的预约领域服务，不查对方的表、不调对方的 HTTP。

A 已交付 `reservation.service.list_for_building(building_id, service_date)`；
字段约定见 docs/14-今晚名单交接.md，集成验收见 tests/test_integration.py。
"""

from __future__ import annotations

from datetime import date

from app.core.errors import not_implemented

CAPABILITY = "reservation.list_for_building"


def reservations_for_building(building_id: str, service_date: date) -> list[dict]:
    try:
        from app.modules.reservation.service import list_for_building
    except ImportError as exc:
        raise not_implemented("M2", CAPABILITY) from exc
    return list_for_building(building_id, service_date)


def reservations_at_summary(building_id,service_date,at):
    from app.modules.reservation.service import list_for_building_at
    return list_for_building_at(building_id,service_date,at)
