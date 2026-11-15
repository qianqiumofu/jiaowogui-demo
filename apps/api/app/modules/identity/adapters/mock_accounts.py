"""合成账号表：固定 ID，两人共用，不得随意改名或换号。

B 的 DirectoryProvider 落地后，住宿/负责/代班关系由目录模块提供，
这里的 home_building_ids 只作为前端壳的占位。
"""

from app.modules.identity.schemas import Person, Role

PEOPLE: list[Person] = [
    Person(
        user_id="usr_synth_0001",
        school_id="2023S0001",
        display_name="张三（学生）",
        login_name="student",
        roles=[Role.STUDENT],
        student_id="stu_synth_0001",
    ),
    Person(
        user_id="usr_synth_0002",
        school_id="T2001",
        display_name="李辅导员（一人多角色）",
        login_name="counselor",
        roles=[Role.COUNSELOR, Role.STUDENT],
        student_id="stu_synth_0009",
    ),
    Person(
        user_id="usr_synth_0003",
        school_id="W3001",
        display_name="王宿管",
        login_name="dorm",
        roles=[Role.DORM_MANAGER],
        home_building_ids=["bldg_a1", "bldg_a2"],
    ),
    Person(
        user_id="usr_synth_0004",
        school_id="G4001",
        display_name="赵园区",
        login_name="campus",
        roles=[Role.CAMPUS],
    ),
]

PEOPLE_BY_LOGIN = {p.login_name: p for p in PEOPLE}
PEOPLE_BY_ID = {p.user_id: p for p in PEOPLE}
DEVICE_TOKENS = {"dev_synth_a1_01": "bldg_a1"}
