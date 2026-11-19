"""合成账号表：固定 ID，两人共用，不得随意改名或换号。

两类账号来源（R18、R19）：
- `UNIFIED_SCHOOL`：学生、辅导员、园区使用者走学校统一身份，默认带合成校内邮箱。
- `STAFF_LOCAL`：宿管是雇佣人员，没有校内账户；此处的 `dorm` 是演示种子，
  运行时由园区经 `/staff-accounts` 注册的新工号落在 `users` 表的 `source=STAFF_LOCAL` 行。

B 的 DirectoryProvider 落地后，住宿/负责/代班关系由目录模块提供，
这里的 home_building_ids 只作为固定管理楼栋的占位，代班范围由 duty 叠加。
"""

from app.modules.identity.schemas import AccountSource, Person, Role

MAIL_DOMAIN = "synth.edu.cn"


def campus_mailbox(school_id: str) -> str:
    """校内邮箱由学号或工号派生，一律合成域名，不采集真实邮箱。"""
    return f"{school_id}@{MAIL_DOMAIN}"


PEOPLE: list[Person] = [
    Person(
        user_id="usr_synth_0001",
        school_id="2023S0001",
        display_name="张三（学生）",
        login_name="student",
        roles=[Role.STUDENT],
        account_source=AccountSource.UNIFIED_SCHOOL,
        email=campus_mailbox("2023S0001"),
        student_id="stu_synth_0001",
    ),
    Person(
        user_id="usr_synth_0002",
        school_id="T2001",
        display_name="李辅导员（一人多角色）",
        login_name="counselor",
        roles=[Role.COUNSELOR, Role.STUDENT],
        account_source=AccountSource.UNIFIED_SCHOOL,
        email=campus_mailbox("T2001"),
        student_id="stu_synth_0009",
    ),
    Person(
        user_id="usr_synth_0004",
        school_id="G4001",
        display_name="赵园区",
        login_name="campus",
        roles=[Role.CAMPUS],
        account_source=AccountSource.UNIFIED_SCHOOL,
        email=campus_mailbox("G4001"),
    ),
    Person(
        user_id="usr_synth_0003",
        school_id="W3001",
        display_name="王宿管（bldg_a1）",
        login_name="dorm",
        roles=[Role.DORM_MANAGER],
        account_source=AccountSource.STAFF_LOCAL,
        email=None,
        home_building_ids=["bldg_a1"],
    ),
]

PEOPLE_BY_LOGIN = {p.login_name: p for p in PEOPLE}
PEOPLE_BY_ID = {p.user_id: p for p in PEOPLE}
# 只有种子账号能反查出姓名；B 的目录落地后由 DirectoryProvider 覆盖。
PEOPLE_BY_STUDENT_ID = {p.student_id: p for p in PEOPLE if p.student_id}
DEVICE_TOKENS = {"dev_synth_a1_01": "bldg_a1"}
