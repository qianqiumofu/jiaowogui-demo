"""园区受控导出（B 主责，R11 + M4「受控导出」）。

- 导出的永远是 `statistics` 的聚合读模型，不落学生明细：联系方式与身份天然不在字段范围内。
- 创建只写 `export_jobs` + 一条 `EXPORT_BUILD` 任务，渲染由 worker 完成（唯一的调度循环归 A）。
- 幂等：`idempotency_key` 命中已有任务时返回同一份资源，不重复排队。
- 保留期 `EXPORT_RETENTION_DAYS`：过期后清空 CSV 内容但保留任务行做审计，下载改判 410。
- 只有发起人能列出与下载自己的导出；园区角色之间的可见范围不做共享。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import ApiError
from app.modules.identity.schemas import SessionContext
from app.modules.statistics import service as statistics

REPORT_STATISTICS = "STATISTICS"
_PARAM_KEYS = (
    "date_from",
    "date_to",
    "college_org_id",
    "park_org_id",
    "building_id",
    "grade",
    "gender",
    "return_source",
    "group_by",
    "attribution",
)
_FILTER_DIMENSIONS = {
    "college_org_id": "college",
    "park_org_id": "park",
    "building_id": "building",
    "grade": "grade",
    "gender": "gender",
    "return_source": "return_source",
}
_METRIC_COLUMNS = ("people", "nights", "returns", "qr_returns", "manual_returns", "enrolled")
_COLUMN_LABELS = {
    "people": "晚归人数",
    "nights": "晚归夜数",
    "returns": "返宿次数",
    "qr_returns": "扫码返宿次数",
    "manual_returns": "人工补录次数",
    "enrolled": "在册人数",
}
_DIMENSION_LABELS = {
    "none": "全校合计",
    "college": "学院",
    "park": "片区",
    "building": "楼栋",
    "grade": "年级",
    "gender": "性别",
    "trend": "业务夜",
}
_ATTRIBUTION_LABELS = {"snapshot": "发生时快照", "current": "当前在册"}

_INSERT_EXPORT_SQL = text(
    """
    INSERT INTO export_jobs (export_id, report, requested_by, params, status, idempotency_key)
    VALUES (:export_id, :report, :requested_by, CAST(:params AS JSONB), 'PENDING', :idempotency_key)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING export_id
    """
)

_INSERT_JOB_SQL = text(
    """
    INSERT INTO background_jobs (id, job_type, business_key, payload, planned_at, status)
    VALUES (:id, 'EXPORT_BUILD', :business_key, CAST(:payload AS JSONB), :planned_at, 'PENDING')
    """
)

_LOAD_SQL = text(
    """
    SELECT export_id, report, requested_by, params, status, file_name, csv_content, row_count,
           error, idempotency_key, created_at, updated_at, done_at, expires_at
    FROM export_jobs
    WHERE export_id = :export_id
    """
)

_LIST_SQL = text(
    """
    SELECT export_id, report, requested_by, params, status, file_name, csv_content, row_count,
           error, idempotency_key, created_at, updated_at, done_at, expires_at
    FROM export_jobs
    WHERE requested_by = :requested_by
    ORDER BY created_at DESC, export_id DESC
    """
)

_DROP_CONTENT_SQL = text(
    "UPDATE export_jobs SET csv_content = NULL, file_name = NULL WHERE export_id = :export_id"
)

_SET_SUCCESS_SQL = text(
    """
    UPDATE export_jobs
    SET status = 'DONE', csv_content = :csv_content, file_name = :file_name, row_count = :row_count,
        error = NULL, done_at = :done_at, expires_at = :expires_at
    WHERE export_id = :export_id AND status <> 'DONE'
    """
)

_SET_FAILURE_SQL = text(
    "UPDATE export_jobs SET status = 'FAILED', error = :error WHERE export_id = :export_id AND status <> 'DONE'"
)


def _business_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(_business_tz()).isoformat()


def _api_error(status_code: int, code: str, message: str, **details: Any) -> ApiError:
    return ApiError(status_code, code, message, details)


def _validation(message: str, **details: Any) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", message, details)


def new_export_id() -> str:
    return f"exp_{uuid.uuid4().hex[:20]}"


def normalize_params(payload: dict) -> dict:
    """只接受统计读模型的口径参数，未知键直接拒：导出范围不能悄悄变宽。"""
    raw = payload.get("params") or {}
    if not isinstance(raw, dict):
        raise _validation("params 必须是对象。")
    unknown = sorted(set(raw) - set(_PARAM_KEYS))
    if unknown:
        raise _validation("params 含不支持的键。", unknown=unknown, allowed=list(_PARAM_KEYS))
    params = {key: raw[key] for key in _PARAM_KEYS if raw.get(key) not in (None, "")}
    params.setdefault("group_by", "park")
    params.setdefault("attribution", "snapshot")
    # 审计要能回答「导的是哪几夜」，所以区间不接受缺省。
    missing = [key for key in ("date_from", "date_to") if not params.get(key)]
    if missing:
        raise _validation("导出必须显式给出业务夜区间。", missing=missing)
    return params


def _check(params: dict) -> tuple[date, date]:
    try:
        return statistics.check_params(
            params.get("date_from"),
            params.get("date_to"),
            params.get("gender"),
            params.get("return_source"),
            params["group_by"],
            params["attribution"],
        )
    except ApiError as exc:
        # 创建时就拒绝口径错误，别让任务排队到 worker 里才失败。
        raise _validation(exc.message, **exc.details) from exc


def create(context: SessionContext, payload: dict, now: datetime) -> dict:
    """登记一次受控导出并排队 `EXPORT_BUILD`；同幂等键返回同一份任务。"""
    report = payload.get("report") or REPORT_STATISTICS
    if report != REPORT_STATISTICS:
        raise _validation("report 目前只支持 STATISTICS（统计口径受控导出）。", value=report)
    params = normalize_params(payload)
    _check(params)
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise _validation("idempotency_key 必须是字符串。")

    with get_engine().begin() as conn:
        if idempotency_key:
            existing = conn.execute(
                text("SELECT export_id FROM export_jobs WHERE idempotency_key = :k"),
                {"k": idempotency_key},
            ).scalar()
            if existing:
                return _resource(conn.execute(_LOAD_SQL, {"export_id": existing}).mappings().one())
        export_id = new_export_id()
        inserted = conn.execute(
            _INSERT_EXPORT_SQL,
            {
                "export_id": export_id,
                "report": REPORT_STATISTICS,
                "requested_by": context.user_id,
                "params": json.dumps(params, ensure_ascii=False),
                "idempotency_key": idempotency_key,
            },
        ).scalar()
        if inserted is None:
            # 并发下同一幂等键已经有人写完：把对方那一行还给调用方。
            rival = conn.execute(
                text("SELECT export_id FROM export_jobs WHERE idempotency_key = :k"),
                {"k": idempotency_key},
            ).scalar()
            return _resource(conn.execute(_LOAD_SQL, {"export_id": rival}).mappings().one())
        conn.execute(
            _INSERT_JOB_SQL,
            {
                "id": f"job_{uuid.uuid4().hex[:20]}",
                "business_key": f"EXPORT_BUILD:{export_id}",
                "payload": json.dumps({"export_id": export_id}, ensure_ascii=False),
                "planned_at": now,
            },
        )
        return _resource(conn.execute(_LOAD_SQL, {"export_id": export_id}).mappings().one())


def list_mine(context: SessionContext, now: datetime) -> dict:
    """只列本人发起的导出；过期行在这里同样会被清成不可下载。"""
    with get_engine().connect() as conn:
        rows = conn.execute(_LIST_SQL, {"requested_by": context.user_id}).mappings().all()
        return {
            "items": [_resource(_forget(conn, dict(row), now)) for row in rows],
            "next_cursor": None,
        }


def get(context: SessionContext, export_id: str, now: datetime) -> dict:
    with get_engine().connect() as conn:
        return _resource(_require(conn, context, export_id, now))


def download(context: SessionContext, export_id: str, now: datetime) -> tuple[str, str]:
    """返回 (文件名, CSV 文本)；生成中 409、失败 409、过期 410、不属于本人 404。"""
    with get_engine().connect() as conn:
        row = _require(conn, context, export_id, now)
        if row["status"] in ("PENDING", "RUNNING"):
            raise _api_error(
                409, "EXPORT_NOT_READY", "导出还在生成中，请稍后重试。",
                export_id=export_id, status=row["status"],
            )
        if row["status"] == "FAILED":
            raise _api_error(
                409, "EXPORT_FAILED", "导出生成失败，请调整口径后重新发起。",
                export_id=export_id, error=row["error"],
            )
        if row["csv_content"] is None:
            # DONE 但没有内容 = 保留期已过、内容已清空。
            raise _api_error(
                410, "EXPORT_EXPIRED", "导出内容已超过保留期，请重新发起。",
                export_id=export_id, expires_at=_iso(row["expires_at"]),
            )
        return row["file_name"] or f"{export_id}.csv", row["csv_content"]


def _require(conn: Connection, context: SessionContext, export_id: str, now: datetime) -> dict:
    row = conn.execute(_LOAD_SQL, {"export_id": export_id}).mappings().first()
    if row is None or row["requested_by"] != context.user_id:
        raise _api_error(
            404,
            "EXPORT_NOT_FOUND",
            "没有这个导出任务，或它不属于当前用户。",
            export_id=export_id,
        )
    return _forget(conn, dict(row), now)


def _forget(conn: Connection, row: dict, now: datetime) -> dict:
    """保留期一到就清空内容，任务行留着做审计：谁在什么时候导了哪个区间。

    清空立即提交，调用方随后因「不可下载」报错也不会把它回滚回去——保留期不是可选项。
    """
    expires_at = row["expires_at"]
    if row["csv_content"] is not None and expires_at is not None and now >= _aware(expires_at):
        conn.execute(_DROP_CONTENT_SQL, {"export_id": row["export_id"]})
        conn.commit()
        row = {**row, "csv_content": None, "file_name": None}
    return row


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=_business_tz())


def build(export_id: str, now: datetime) -> None:
    """worker 侧渲染：读统计读模型 → CSV → 落库。已完成的行不再重复生成。"""
    with get_engine().begin() as conn:
        row = conn.execute(_LOAD_SQL, {"export_id": export_id}).mappings().first()
        if row is None or row["status"] == "DONE":
            return
        conn.execute(
            text("UPDATE export_jobs SET status = 'RUNNING' WHERE export_id = :id"), {"id": export_id}
        )
        try:
            body = statistics.query(conn, **dict(row["params"]))
            csv_text, data_rows = render_csv(conn, body)
        except ApiError as exc:
            # 口径非法是可解释的终态：落 FAILED 让园区改条件重发，而不是无限重试。
            conn.execute(
                _SET_FAILURE_SQL, {"export_id": export_id, "error": f"{exc.code}: {exc.message}"[:500]}
            )
            return
        retention = timedelta(days=get_settings().export_retention_days)
        conn.execute(
            _SET_SUCCESS_SQL,
            {
                "export_id": export_id,
                "csv_content": csv_text,
                "file_name": file_name(body),
                "row_count": data_rows,
                "done_at": now,
                "expires_at": now + retention,
            },
        )


def file_name(body: dict) -> str:
    group = body["group_by"]
    return (
        f"jiaowogui_statistics_"
        f"{body['range']['date_from'].replace('-', '')}-{body['range']['date_to'].replace('-', '')}"
        f"_{group}.csv"
    )


def _data_rows(body: dict) -> list[dict]:
    """趋势分组的数据在 `by_day` 里，其余维度在 `rows` 里；CSV 只认带展示名的那一套。"""
    if body["group_by"] == "trend":
        return [{"label": row["service_date"], **row} for row in body["by_day"]]
    return body["rows"]


def render_csv(conn: Connection, body: dict) -> tuple[str, int]:
    """聚合结果 → (带口径说明的 CSV, 数据行数)。预约两列因来源未落地而不进文件，不用空列冒充。"""
    options = statistics.Options(conn)
    rows = _data_rows(body)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["报表", "全校晚归统计（受控导出）"])
    writer.writerow(["业务夜区间", f"{body['range']['date_from']} 至 {body['range']['date_to']}"])
    writer.writerow(["归属口径", _ATTRIBUTION_LABELS.get(body["attribution"], body["attribution"])])
    dimension = _DIMENSION_LABELS.get(body["group_by"], body["group_by"])
    writer.writerow(["分组维度", dimension])
    writer.writerow(["筛选", _filters_text(options, body["filters"])])
    writer.writerow(["数据缺口", "预约与未确认统计的来源未落地，本文件不含这两列"])
    writer.writerow([])
    writer.writerow([dimension, *[_COLUMN_LABELS[key] for key in _METRIC_COLUMNS]])
    for row in rows:
        writer.writerow([row["label"], *[row[key] for key in _METRIC_COLUMNS]])
    if body["group_by"] != "none":
        writer.writerow(["合计", *[body["totals"][key] for key in _METRIC_COLUMNS]])
    return "\ufeff" + buffer.getvalue(), len(rows)


def _filters_text(options: statistics.Options, filters: dict[str, str]) -> str:
    if not filters:
        return "无"
    parts = []
    for key, value in filters.items():
        label = value
        if key == "return_source":
            label = {"QR": "扫码返宿", "MANUAL": "人工补录"}.get(value, value)
        elif dimension := _FILTER_DIMENSIONS.get(key):
            label = options.label(dimension, value)
        parts.append(f"{key}={label}")
    return "；".join(parts)


def _resource(row: dict) -> dict:
    return {
        "export_id": row["export_id"],
        "report": row["report"],
        "status": row["status"],
        "requested_by": row["requested_by"],
        "params": row["params"],
        "file_name": row["file_name"],
        "row_count": row["row_count"],
        "error": row["error"],
        "idempotency_key": row["idempotency_key"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "done_at": _iso(row["done_at"]),
        "expires_at": _iso(row["expires_at"]),
        "downloadable": row["status"] == "DONE" and row["csv_content"] is not None,
    }
