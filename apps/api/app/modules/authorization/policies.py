"""动作到角色的映射；数据范围由 scope 承载，两者都必须满足才放行。

新增动作在此登记并同步 contracts/openapi.yaml，不得在路由里写 if role == ...
"""

from app.modules.identity.schemas import Role

ACTIONS: dict[str, set[Role]] = {
    # A：学生端
    "reservation:create": {Role.STUDENT},
    "reservation:update": {Role.STUDENT},
    "reservation:cancel": {Role.STUDENT},
    "reservation:restore": {Role.STUDENT},
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
    "manual_return:create": {Role.DORM_MANAGER},
    "duty:read": {Role.DORM_MANAGER, Role.COUNSELOR},
    "duty:switch": {Role.DORM_MANAGER},
    "campus:query": {Role.CAMPUS},
    "statistics:read": {Role.CAMPUS},
    "export:create": {Role.CAMPUS},
    "risk:config": {Role.CAMPUS},
    # R19：宿管工号账号的注册、改绑、重置与停用只属于园区，其他角色一律无入口。
    "staff_account:create": {Role.CAMPUS},
    "staff_account:read": {Role.CAMPUS},
    "staff_account:update": {Role.CAMPUS},
    "staff_account:reset": {Role.CAMPUS},
    "staff_account:disable": {Role.CAMPUS},
    # A：通知与模拟收件箱。学生端不进收件箱（R15 禁止超时提醒，R16 只在申请时弹窗）。
    "notification:read": {Role.DORM_MANAGER, Role.COUNSELOR, Role.CAMPUS},
    "notification:mark_read": {Role.DORM_MANAGER, Role.COUNSELOR, Role.CAMPUS},
    # 演示投递入口：正式版收件人由目录与值班关系派生，不开放自选。
    "notification:dispatch": {Role.CAMPUS},
    "notification_job:read": {Role.CAMPUS},
}


def is_allowed(role: Role, action: str) -> bool:
    return role in ACTIONS.get(action, set())


def allowed_actions(role: Role) -> list[str]:
    return sorted(a for a, roles in ACTIONS.items() if role in roles)
