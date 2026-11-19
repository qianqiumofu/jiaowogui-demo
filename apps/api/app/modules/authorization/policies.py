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
    "contact:read_duty": {Role.DORM_MANAGER},
    "building_residents:read_duty": {Role.DORM_MANAGER},
    "manual_return:create": {Role.DORM_MANAGER},
    "duty:read": {Role.DORM_MANAGER, Role.COUNSELOR},
    "duty:switch": {Role.DORM_MANAGER},
    "campus:query": {Role.CAMPUS},
    "statistics:read": {Role.CAMPUS, Role.COUNSELOR, Role.IDEOLOGY, Role.COLLEGE_ADMIN},
    "export:create": {Role.CAMPUS, Role.COUNSELOR, Role.IDEOLOGY, Role.COLLEGE_ADMIN},
    "export:delete": {Role.CAMPUS, Role.COUNSELOR, Role.IDEOLOGY, Role.COLLEGE_ADMIN},
    "risk:config": {Role.CAMPUS},
    # R19：宿管工号账号的注册、改绑、重置与停用只属于园区，其他角色一律无入口。
    "staff_account:create": {Role.CAMPUS},
    "staff_account:read": {Role.CAMPUS},
    "staff_account:update": {Role.CAMPUS},
    "staff_account:reset": {Role.CAMPUS},
    "staff_account:disable": {Role.CAMPUS},
    "staff_account:enable": {Role.CAMPUS},
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

# 专职思政按明确负责关系工作；学院负责人读学院范围，不默认成为风险收件人。
for _action,_roles in ACTIONS.items():
    if Role.COUNSELOR in _roles:
        _roles.add(Role.IDEOLOGY)
        if _action not in ("risk:ack","report:subscribe"):
            _roles.add(Role.COLLEGE_ADMIN)
ACTIONS.update({
    "identity:profile":set(Role),
    "permission:manage":{Role.AUTH_ADMIN,Role.COLLEGE_ADMIN},
    "directory:students":{Role.COUNSELOR,Role.IDEOLOGY,Role.COLLEGE_ADMIN,Role.AUTH_ADMIN,Role.CAMPUS},
    "return:correct":{Role.DORM_MANAGER},
    "duty:assign":{Role.CAMPUS},
})
# 园区管理宿管；宿管只读取指派，不可自授跨楼栋范围。
ACTIONS["duty:switch"]={Role.CAMPUS}

ACTIONS["duty:read"].add(Role.CAMPUS)

ACTIONS["return:read_evidence"]={Role.STUDENT,Role.COUNSELOR,Role.IDEOLOGY,Role.COLLEGE_ADMIN,Role.DORM_MANAGER}

# 用户确认：校级只任免学院负责人，可只读查看全校晚归日报周报。
ACTIONS["report:read"].add(Role.AUTH_ADMIN)
ACTIONS["report:statistics"] = {Role.AUTH_ADMIN}
ACTIONS['risk:follow_up'] = {Role.COUNSELOR,Role.IDEOLOGY,Role.DORM_MANAGER}
