"""保留业务状态地升级仓库千人合成快照；不处理真实目录或未知档案。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.db.models import Building, Organization, Student
from app.db.seed import BUILDINGS, PARKS


def upgrade_snapshot(engine) -> dict[str, int]:
    """仅补演示目录和已知千人生成器的缺失层次；已有字段与业务流水保留。"""
    with Session(engine) as db, db.begin():
        students = list(db.scalars(select(Student).order_by(Student.student_id)))
        expected = {f"stu_synth_{n:04d}" for n in range(1, 1001)}
        if {row.student_id for row in students} != expected:
            raise ValueError("仅支持仓库的 1000 人合成快照；未修改其他数据集。")
        for row in students:
            n = int(row.student_id.rsplit("_", 1)[1])
            if row.display_name != f"合成学生{n:04d}":
                raise ValueError("发现非原始合成档案，拒绝推断培养层次。")
        for org_id, name in PARKS:
            db.execute(insert(Organization).values(org_id=org_id, name=name, org_type="CAMPUS_PARK")
                       .on_conflict_do_nothing(index_elements=["org_id"]))
        for building_id, park_id, name, code in BUILDINGS:
            db.execute(insert(Building).values(building_id=building_id, campus_org_id=park_id, name=name, code=code)
                       .on_conflict_do_update(index_elements=["building_id"], set_={
                           "campus_org_id": park_id, "name": name, "code": code}))
        filled = 0
        for row in students:
            if row.education_level is None:
                index = int(row.student_id.rsplit("_", 1)[1]) - 1
                class_index = index % 200 // 25
                row.education_level = ("BACHELOR", "MASTER", "DOCTORAL")[class_index % 3]
                filled += 1
    return {"catalog_buildings": len(BUILDINGS), "education_filled": filled}


if __name__ == "__main__":
    print(upgrade_snapshot(get_engine()))
