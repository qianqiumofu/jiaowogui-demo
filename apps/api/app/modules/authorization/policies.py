"""动作到角色的映射；数据范围由 scope 承载，两者都必须满足才放行。

新增动作在此登记并同步 contracts/openapi.yaml，不得在路由里写 if role == ...
"""

from app.modules.identity.schemas import Role

ACTIONS: dict[str, set[Role]] = {
    # A：学生端
    "reservation:create": {Role.STUDENT},
    "reservation:update": {Role.STUDENT},
    "reservation:cancel": {Role.STUDENT},
    "reservation:read": {Role.STUDENT, Role.DORM_MANAGER, Role.COUNSELOR},
    "verification:create": {Role.STUDENT},
    "pass:display": {Role.STUDENT},
    "return:read_self": {Role.STUDENT},
    # A：辅导员端
    "return:read_scoped": {Role.COUNSELOR, Role.DORM_MANAGER},
    "report:read": {Role.COUNSELOR},
    "report:subscribe": {Role.COUNSELOR},
    "risk:read": {Role.COUNSELOR, Role.DORM_MANAGER, Role.CAMPUS},
    "risk:ack": {Role.COUNSELOR, Role.DORM_MANAGER},
    # B：宿管端与园区端
    "building:tonight": {Role.DORM_MANAGER},
    "contact:read_duty": {Role.DORM_MANAGER},
    "building_residents:read_duty": {Role.DORM_MANAGER},
    "manual_return:create": {Role.DORM_MANAGER},
    "duty:read": {Role.DORM_MANAGER, Role.COUNSELOR},
    "duty:switch": {Role.DORM_MANAGER},
    "campus:query": {Role.CAMPUS},
    "statistics:read": {Role.CAMPUS},
    "export:create": {Role.CAMPUS},
    "risk:config": {Role.CAMPUS},
}


def is_allowed(role: Role, action: str) -> bool:
    return role in ACTIONS.get(action, set())


def allowed_actions(role: Role) -> list[str]:
    return sorted(a for a, roles in ACTIONS.items() if role in roles)
