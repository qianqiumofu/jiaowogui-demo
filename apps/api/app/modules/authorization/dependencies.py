from collections.abc import Callable

from fastapi import Depends

from app.core.errors import ApiError
from app.modules.authorization.policies import is_allowed
from app.modules.identity.dependencies import get_session_context
from app.modules.identity.schemas import SessionContext


def authorize(context: SessionContext, action: str) -> None:
    if not is_allowed(context.active_role, action):
        raise ApiError(
            403,
            "FORBIDDEN_ACTION",
            "当前角色没有该操作权限。",
            {"action": action, "role": context.active_role.value},
        )
    scope = context.scope
    if context.active_role.value == "STUDENT" and not scope.get("student_id"):
        raise ApiError(
            403,
            "SCOPE_UNRESOLVED",
            "住宿归属未同步，无法进行晚归业务。",
            {"action": action},
        )
    if context.active_role.value == "COUNSELOR" and str(
        scope.get("resolved_by", "")
    ).startswith("pending"):
        raise ApiError(
            403,
            "SCOPE_UNRESOLVED",
            "负责关系尚未由目录同步，暂无法查询负责学生。",
            {"action": action, "resolved_by": scope.get("resolved_by")},
        )


def require(action: str) -> Callable[[SessionContext], SessionContext]:
    def dependency(context: SessionContext = Depends(get_session_context)) -> SessionContext:
        authorize(context, action)
        return context

    return dependency


def require_own_resource(action: str) -> Callable[[SessionContext], SessionContext]:
    """只校验动作授予，跳过目录派生范围检查。

    给「范围天然等于本人」的读入口用（模拟收件箱）：数据范围由 user_id 定死，
    不依赖 B 的目录关系；服务层一律按 recipient_user_id == 当前 user_id 过滤。
    """

    def dependency(context: SessionContext = Depends(get_session_context)) -> SessionContext:
        if not is_allowed(context.active_role, action):
            raise ApiError(
                403,
                "FORBIDDEN_ACTION",
                "当前角色没有该操作权限。",
                {"action": action, "role": context.active_role.value},
            )
        return context

    return dependency
