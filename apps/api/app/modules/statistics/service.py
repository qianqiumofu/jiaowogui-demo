"""园区端全校晚归统计（B 主责，R14 + 基线「园区统计口径」）。

- 晚归事实只认 `return_records`（`QR` 与 `MANUAL` 都算，R10、R11）；领码、核验、申请、
  取消、未确认都不计实际晚归（R15）。
- 三值：人数 = 去重学生；晚归夜数 = 去重（学生 × 业务夜）；返宿次数 = 记录条数。
- 归属默认按业务夜发生时快照：住宿用 `residences` 生效区间，年级沿用目录登记的入学年份；
  `attribution=current` 用当前在册行（`residences.valid_to IS NULL`、`students` 登记值）。
  性别、学院与年级不保留历史值，两种口径同源——接真实档案后换成历史映射。
- A 的 `reservations` 未落地：预约两列返回 null 并登记 `data_gaps`，不返回 0 冒充没人预约。
- 演示规模（在册几十人、几十夜）一次取事实行、在进程内聚合，动态 SQL 只有一种形状。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.errors import ApiError
from app.modules.directory import service as directory
from app.modules.returns import service as returns

GENDERS = ("MALE", "FEMALE")
RETURN_SOURCES = ("QR", "MANUAL")
GROUP_BY = ("none", "college", "park", "building", "grade", "gender", "trend")
ATTRIBUTIONS = ("snapshot", "current")
RESERVATION_GAP = "RESERVATION_SOURCE_UNAVAILABLE"

_GENDER_LABELS = {"MALE": "男生", "FEMALE": "女生"}
# 一条晚归事实：学生、业务夜、当晚年级、快照/当前楼栋、学院、性别、返宿来源。
# 目录不存年级历史，`night_grade` 与 `enrolled_grade` 同源；residence LEFT JOIN 保留
# 归属缺失的脏数据，宁可让人数少计也不虚增分组。

# 在册名册（分母）两条形状：区间名册（组内 enrolled 与总计）与单夜名册（趋势分母）。
# 拆开写是因为同一绑定参数在一条语句里多处出现时，Postgres 无法推断裸 `:night` 的类型。




def _api_error(message: str, **details: Any) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", message, details)


def _validate(gender: str | None, return_source: str | None, group_by: str, attribution: str) -> None:
    if group_by not in GROUP_BY:
        raise _api_error("group_by 只支持契约里的维度。", allowed=list(GROUP_BY))
    if attribution not in ATTRIBUTIONS:
        raise _api_error("attribution 只能是 snapshot 或 current。", value=attribution)
    if gender is not None and gender not in GENDERS:
        raise _api_error("gender 取值不合法。", allowed=list(GENDERS))
    if return_source is not None and return_source not in RETURN_SOURCES:
        raise _api_error("return_source 取值不合法。", allowed=list(RETURN_SOURCES))


def _parse_date(value: str | None, name: str) -> date:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError as exc:
        raise _api_error("业务夜日期格式应为 YYYY-MM-DD。", param=name) from exc


def check_params(
    date_from: str | None,
    date_to: str | None,
    gender: str | None,
    return_source: str | None,
    group_by: str,
    attribution: str,
) -> tuple[date, date]:
    """校验口径参数并归一化成起止业务夜。

    公开给导出等下游调用方复用，避免「导出创建了、worker 构建时才发现参数非法」。
    """
    _validate(gender, return_source, group_by, attribution)
    night_to = _parse_date(date_to, "date_to")
    night_from = _parse_date(date_from or date_to, "date_from")
    if night_from > night_to:
        raise _api_error(
            "date_from 不得晚于 date_to。",
            date_from=night_from.isoformat(),
            date_to=night_to.isoformat(),
        )
    return night_from, night_to


class Options:
    """目录维度取值到展示名的映射；缺行时退回显示 ID，不因目录不全而报错。"""

    def __init__(self, conn: Connection) -> None:
        catalog=directory.filter_catalog(conn)
        self.colleges={r["org_id"]:r["name"] for r in catalog["colleges"]}
        self.parks={r["org_id"]:r["name"] for r in catalog["parks"]}
        self.building_park={r["building_id"]:r["park_org_id"] for r in catalog["buildings"]}
        self.buildings={r["building_id"]:r["name"] for r in catalog["buildings"]}

    def park_of(self, building_id: str | None) -> str | None:
        return self.building_park.get(building_id) if building_id else None

    def label(self, dimension: str, value: Any) -> str:
        if value is None:
            return "全部"
        if dimension == "college":
            return self.colleges.get(value, str(value))
        if dimension == "park":
            return self.parks.get(value, str(value))
        if dimension == "building":
            return self.buildings.get(value, str(value))
        if dimension == "gender":
            return _GENDER_LABELS.get(value, str(value))
        return str(value)


def _keep(row: dict, filters: dict[str, str], attribution: str, options: Options) -> bool:
    """同一套筛选同时作用在晚归事实行与在册名册行上，两类行的楼栋字段名不同。"""
    building = _building_of(row, attribution)
    if filters.get("college_org_id") and row["college_org_id"] != filters["college_org_id"]:
        return False
    if filters.get("gender") and row["gender"] != filters["gender"]:
        return False
    if filters.get("grade") and _grade(row, attribution) != filters["grade"]:
        return False
    if filters.get("building_id") and building != filters["building_id"]:
        return False
    if filters.get("park_org_id") and options.park_of(building) != filters["park_org_id"]:
        return False
    # 来源只存在于晚归事实行；名册行不带 source，据此放开，避免筛来源时把在册分母清零。
    if "source" in row and filters.get("return_source") and row["source"] != filters["return_source"]:
        return False
    return True


def _building_of(row: dict, attribution: str) -> str | None:
    if "building_id" in row:  # 在册名册行：区间名册已按 attribution 过滤，单夜名册按当晚住宿取值。
        return row["current_building_id"] if "current_building_id" in row else row["building_id"]
    return row["current_building_id"] if attribution == "current" else row["night_building_id"]


def _grade(row: dict, attribution: str) -> str:
    # 年级 = 目录登记的入学年份（`students.grade` 原值）。
    # 快照与 current 两口径同源：`students` 不保留年级历史，接真实档案后再按业务夜取历史值。
    if attribution == "current":
        return str(row.get("enrolled_grade") or row.get("grade_key") or row.get("grade") or "")
    return str(row.get("night_grade") or row.get("grade_key") or row.get("grade") or "")


def _key(row: dict, dimension: str, attribution: str, options: Options) -> Any:
    if dimension == "college":
        return row["college_org_id"]
    if dimension == "park":
        return options.park_of(_building_of(row, attribution))
    if dimension == "building":
        return _building_of(row, attribution)
    if dimension == "gender":
        return row["gender"]
    if dimension == "grade":
        return _grade(row, attribution)
    return None


def _new_bucket() -> dict:
    return {"students": set(), "nights": set(), "returns": defaultdict(int)}


def _add_fact(bucket: dict, row: dict) -> None:
    bucket["students"].add(row["student_id"])
    bucket["nights"].add((row["student_id"], row["service_date"]))
    bucket["returns"][row["source"]] += 1


def _metrics(bucket: dict, enrolled: list[dict]) -> dict:
    return {
        "people": len(bucket["students"]),
        "nights": len(bucket["nights"]),
        "returns": sum(bucket["returns"].values()),
        "qr_returns": bucket["returns"].get("QR", 0),
        "manual_returns": bucket["returns"].get("MANUAL", 0),
        "enrolled": len({row["student_id"] for row in enrolled}),
        "reservations": None,
        "unconfirmed": None,
    }


def _rows(
    buckets: dict,
    enrolled_by_key: dict,
    dimension: str,
    options: Options,
) -> list[dict]:
    out = [
        {
            "value": value,
            "label": options.label(dimension, value),
            **_metrics(bucket, enrolled_by_key.get(value, [])),
        }
        for value, bucket in buckets.items()
    ]
    out.sort(key=lambda item: (-item["nights"], -item["returns"], item["label"]))
    return out


def query(
    conn: Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    college_org_id: str | None = None,
    park_org_id: str | None = None,
    building_id: str | None = None,
    grade: str | None = None,
    gender: str | None = None,
    return_source: str | None = None,
    group_by: str = "park",
    attribution: str = "snapshot",
) -> dict:
    """园区统计读模型：三值分列 + 分组明细 + 逐日趋势。"""
    night_from, night_to = check_params(date_from, date_to, gender, return_source, group_by, attribution)

    filters = {
        key: value
        for key, value in {
            "college_org_id": college_org_id,
            "park_org_id": park_org_id,
            "building_id": building_id,
            "grade": grade,
            "gender": gender,
            "return_source": return_source,
        }.items()
        if value
    }
    options = Options(conn)
    params = {"date_from": night_from, "date_to": night_to}

    late_rows = [
        dict(row)
        for row in _late_facts(conn,night_from,night_to)
        if _keep(dict(row), filters, attribution, options)
    ]

    buckets: dict[Any, dict] = defaultdict(_new_bucket)
    enrolled_by_key: dict[Any, list[dict]] = defaultdict(list)
    totals = _new_bucket()

    if group_by == "trend":
        rows = []
        for row in late_rows:
            _add_fact(buckets[row["service_date"]], row)
            _add_fact(totals, row)
    else:
        for row in late_rows:
            key = None if group_by == "none" else _key(row, group_by, attribution, options)
            _add_fact(buckets[key], row)
            _add_fact(totals, row)

    by_day = _by_day(buckets if group_by == "trend" else _night_buckets(late_rows),
                     conn, night_from, night_to, filters, attribution, options)
    enrolled_range = [
        row
        for row in _enrolled_range(conn, night_from, night_to, attribution)
        if _keep(row, filters, attribution, options)
    ]
    if group_by == "none":
        rows = _rows(buckets, {None: enrolled_range}, "none", options)
    elif group_by != "trend":
        for row in enrolled_range:
            enrolled_by_key[_key(row, group_by, attribution, options)].append(row)
        rows = _rows(buckets, enrolled_by_key, group_by, options)

    from app.modules.reports.readmodel import statistic_facts
    reservation_rows = [r for r in statistic_facts(conn, start=night_from, end=night_to) if _keep(r, filters, attribution, options)]
    def counts(items):
        return {"reservations": len({r["student_id"] for r in items}), "unconfirmed": len({r["student_id"] for r in items if r["unconfirmed"]})}
    if group_by != "trend":
        keyed = {r["value"]: r for r in rows}
        for fact in reservation_rows:
            key = None if group_by == "none" else _key(fact, group_by, attribution, options)
            if key not in keyed:
                keyed[key] = {"value": key, "label": options.label(group_by, key), **_metrics(_new_bucket(), enrolled_by_key.get(key, enrolled_range if group_by == "none" else []))}
        rows = list(keyed.values())
        for row in rows:
            row.update(counts([r for r in reservation_rows if (None if group_by == "none" else _key(r, group_by, attribution, options)) == row["value"]]))
        rows.sort(key=lambda r: (-r["nights"], -r["returns"], r["label"]))
    days = {r["service_date"]: r for r in by_day}
    for fact in reservation_rows:
        day = fact["service_date"].isoformat()
        if day not in days:
            enrolled = [r for r in _enrolled_night(conn, fact["service_date"]) if _keep(r, filters, attribution, options)]
            days[day] = {"service_date": day, **_metrics(_new_bucket(), enrolled)}
    by_day = [days[k] for k in sorted(days)]
    for row in by_day:
        row.update(counts([r for r in reservation_rows if r["service_date"].isoformat() == row["service_date"]]))
    total_metrics = _metrics(totals, enrolled_range)
    total_metrics.update(counts(reservation_rows))
    return {
        "group_by": group_by,
        "attribution": attribution,
        "range": {"date_from": night_from.isoformat(), "date_to": night_to.isoformat()},
        "filters": filters,
        "totals": total_metrics,
        "rows": rows,
        "by_day": by_day,
        "data_gaps": [],
    }


def _night_buckets(late_rows: list[dict]) -> dict:
    buckets: dict[Any, dict] = defaultdict(_new_bucket)
    for row in late_rows:
        _add_fact(buckets[row["service_date"]], row)
    return buckets


def _enrolled_range(
    conn: Connection, night_from: date, night_to: date, attribution: str
) -> list[dict]:
    return directory.enrolled_range(conn,night_from,night_to,attribution)


def _enrolled_night(conn: Connection, night: date) -> list[dict]:
    return directory.enrolled_night(conn,night)



def _by_day(
    buckets: dict,
    conn: Connection,
    night_from: date,
    night_to: date,
    filters: dict[str, str],
    attribution: str,
    options: Options,
) -> list[dict]:
    out = []
    for night in sorted(buckets):
        bucket = buckets[night]
        enrolled = [
            row
            for row in _enrolled_night(conn, night)
            if _keep(row, filters, attribution, options)
        ]
        out.append({"service_date": night.isoformat(), **_metrics(bucket, enrolled)})
    return out


def filters(conn: Connection) -> dict:
    """筛选器选项：学院、片区（含楼栋数）、楼栋、年级、性别、晚归来源。"""
    return directory.filter_catalog(conn)


def _late_facts(conn,start,end):
    dimensions={}
    for fact in returns.statistic_rows(conn,start,end):
        night=fact["service_date"]
        if night not in dimensions:dimensions[night]=directory.statistic_students(conn,night)
        meta=dimensions[night].get(fact["student_id"])
        if meta:yield {**meta,**fact}
