"""受控导出接口（B 主责）：园区发起，worker 生成，只有发起人能列出与下载。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.modules.authorization.dependencies import require
from app.modules.exports import service
from app.modules.identity.schemas import SessionContext

router = APIRouter(prefix="/exports", tags=["exports"])

GuardedDep = Annotated[SessionContext, Depends(require("export:create"))]
DeleteDep = Annotated[SessionContext, Depends(require("export:delete"))]


@router.delete('/{export_id}')
def delete_export(export_id: str, guarded: DeleteDep, request: Request) -> dict:
    return service.delete(guarded, export_id, request.app.state.clock.now())


@router.post("", status_code=status.HTTP_201_CREATED)
def create_export(payload: dict, guarded: GuardedDep, request: Request) -> dict:
    """排队一次统计口径导出；同一 `idempotency_key` 重复提交返回同一任务。"""
    return service.create(guarded, payload or {}, request.app.state.clock.now())


@router.get("")
def list_exports(guarded: GuardedDep, request: Request) -> dict:
    """本人的导出任务，新的在前。"""
    return service.list_mine(guarded, request.app.state.clock.now())


@router.get("/{export_id}")
def get_export(export_id: str, guarded: GuardedDep, request: Request) -> dict:
    return service.get(guarded, export_id, request.app.state.clock.now())


@router.get("/{export_id}/download")
def download_export(export_id: str, guarded: GuardedDep, request: Request) -> Response:
    """CSV 下载。生成中 409、失败 409、超过保留期 410、不是本人的任务 404。"""
    file_name, content = service.download(guarded, export_id, request.app.state.clock.now())
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Cache-Control": "no-store",
        },
    )
