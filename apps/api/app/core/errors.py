"""统一错误信封：code / message / request_id / details。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def not_implemented(stage: str, what: str) -> ApiError:
    return ApiError(
        501,
        "NOT_IMPLEMENTED",
        "该能力尚未实现，属于框架占位。",
        {"stage": stage, "capability": what},
    )


def unauthorized(message: str = "请先登录。") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", message)


def forbidden(action: str) -> ApiError:
    return ApiError(
        status.HTTP_403_FORBIDDEN,
        "FORBIDDEN_ACTION",
        "当前角色没有该操作权限。",
        {"action": action},
    )


def out_of_scope(resource_type: str, resource_id: str, allowed: list[str]) -> ApiError:
    return ApiError(
        status.HTTP_403_FORBIDDEN,
        "OUT_OF_SCOPE",
        "目标不在当前有效数据范围内。",
        {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "allowed": allowed,
        },
    )


def database_unavailable() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "DATABASE_UNAVAILABLE",
        "数据库未启动，本接口需要 PostgreSQL。",
        {"hint": "启动 docker compose up -d postgres"},
    )


def error_body(code: str, message: str, request_id: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "request_id": request_id, "details": details}


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, _request_id(request), exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                "VALIDATION_FAILED",
                "请求参数不符合契约。",
                _request_id(request),
                {"errors": [str(e.get("loc")) for e in exc.errors()]},
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "INTERNAL_ERROR",
                "服务内部错误。",
                _request_id(request),
                {"exception": type(exc).__name__},
            ),
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", uuid.uuid4().hex)
