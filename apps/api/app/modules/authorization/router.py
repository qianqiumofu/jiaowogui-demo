"""权限自省接口（A 主责）：供前端折叠无权入口。"""

from fastapi import APIRouter

from app.modules.authorization.dependencies import authorize
from app.modules.authorization.policies import ACTIONS, is_allowed
from app.modules.identity.dependencies import ContextDep
from app.modules.identity.schemas import Role

router = APIRouter(prefix="/authz", tags=["authorization"])


@router.get("/actions")
def list_actions(context: ContextDep) -> dict:
    allowed = sorted(a for a, roles in ACTIONS.items() if is_allowed(context.active_role, a))
    return {"role": context.active_role.value, "allowed_actions": allowed}


@router.get("/scope-check")
def scope_check(context: ContextDep, action: str = "reservation:create") -> dict:
    authorize(context, action)
    return {
        "role": context.active_role.value,
        "action": action,
        "decision": "ALLOWED",
        "scope": context.scope,
    }


@router.get("/roles")
def list_roles() -> dict:
    return {"items": [{"value": r.value} for r in Role], "next_cursor": None}
