"""真实 PostgreSQL 验证合成快照升级保留业务数据且不猜未知档案。"""
import pytest
from sqlalchemy import insert, select, text

from app.core.db import get_engine
from app.db.models import Student
from app.db.upgrade_demo_snapshot import upgrade_snapshot

pytestmark = pytest.mark.usefixtures("seeded_demo_db")


def test_upgrade_refuses_non_thousand_dataset_without_modifying_it():
    with get_engine().connect() as conn:
        before = conn.execute(text("SELECT count(*), count(education_level) FROM students")).one()
        with pytest.raises(ValueError, match="1000"):
            upgrade_snapshot(conn)
        assert conn.execute(text("SELECT count(*), count(education_level) FROM students")).one() == before


def test_upgrade_fills_only_missing_synthetic_fields_and_is_idempotent():
    with get_engine().connect() as conn, conn.begin():
        # 用原固定种子补成仅含目录的千人集合，不重新生成业务流水。
        conn.execute(text("UPDATE students SET display_name='合成学生' || right(student_id,4), education_level=NULL"))
        conn.execute(insert(Student), [dict(
            student_id=f"stu_synth_{n:04d}", school_id=f"SNAP-{n:04d}",
            display_name=f"合成学生{n:04d}", college_org_id="org_college_cs",
            grade="2023", gender="MALE", phone="SYNTHETIC") for n in range(67, 1001)])
        conn.execute(text("UPDATE students SET education_level='DOCTORAL' WHERE student_id='stu_synth_0001'"))
        returns_before = conn.execute(text("SELECT count(*) FROM return_records")).scalar_one()
        accounts_before = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
        result = upgrade_snapshot(conn)
        assert result == {"catalog_buildings": 107, "education_filled": 999}
        assert conn.scalar(select(Student.education_level).where(Student.student_id == "stu_synth_0001")) == "DOCTORAL"
        assert conn.execute(text("SELECT count(*) FROM students WHERE education_level IS NULL")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM buildings")).scalar_one() == 107
        assert conn.execute(text("SELECT count(*) FROM return_records")).scalar_one() == returns_before
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == accounts_before
        assert upgrade_snapshot(conn)["education_filled"] == 0
        # 外层回滚保证此文件不改变其他模块使用的固定种子。
        conn.rollback()


def test_upgrade_rejects_changed_directory_before_any_write():
    with get_engine().connect() as conn, conn.begin():
        conn.execute(text("UPDATE students SET display_name='合成学生' || right(student_id,4)"))
        conn.execute(insert(Student), [dict(
            student_id=f"stu_synth_{n:04d}", school_id=f"SNAP-{n:04d}",
            display_name=f"合成学生{n:04d}", college_org_id="org_college_cs",
            grade="2023", gender="MALE", phone="SYNTHETIC") for n in range(67, 1001)])
        conn.execute(text("UPDATE students SET display_name='合成自定义学生' WHERE student_id='stu_synth_1000'"))
        with pytest.raises(ValueError, match="非原始合成"):
            upgrade_snapshot(conn)
        conn.rollback()
