"""空库、A 旧头升级及账号搬迁回退；在真实 PG 的独立临时 schema 中执行。"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.db import get_engine


@pytest.mark.parametrize("old_a_database", [False, True])
def test_migration_preserves_legacy_a_accounts_and_roundtrips(postgres_schema, old_a_database):
    api = Path(__file__).resolve().parents[1]
    cfg = Config(str(api / "alembic.ini"))
    cfg.set_main_option("script_location", str(api / "alembic"))
    schema = "jwg_migration_test_" + uuid4().hex
    engine = get_engine()
    created = datetime(2026, 11, 10, 19, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        cfg.attributes["connection"] = conn
        if old_a_database:
            command.upgrade(cfg, "0003")
            conn.execute(text("""
                INSERT INTO local_staff_accounts
                (id, login_name, display_name, password, building_ids, status, created_at, updated_at)
                VALUES (:id, :login, :name, 'synth_only',
                        '["bldg_a1"]', 'ACTIVE', :at, :at)
            """), {"at": created, "id": "usr_staff_" + "x" * 24, "login": "x" * 64, "name": "合" * 80})
        command.upgrade(cfg, "head")
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0018"
        assert conn.execute(text("SELECT to_regclass('local_staff_accounts')")).scalar() is None
        if old_a_database:
            row = conn.execute(text("SELECT * FROM users WHERE source='STAFF_LOCAL'")).mappings().one()
            assert row["source"] == "STAFF_LOCAL" and row["password"] == "synth_only"
            assert row["building_ids"] == ["bldg_a1"] and row["created_at"] == created
            conn.execute(text("UPDATE users SET school_id='legacy_synth', login_name='legacy_synth', display_name='合成旧账号' WHERE source='STAFF_LOCAL'"))
            command.downgrade(cfg, "b0009")
            assert conn.execute(text("SELECT created_at FROM local_staff_accounts")).scalar() == created
            assert conn.execute(text("SELECT count(*) FROM users WHERE user_id LIKE 'usr_staff_%'")).scalar() == 0
            command.upgrade(cfg, "head")
            assert conn.execute(text("SELECT count(*) FROM users WHERE source='STAFF_LOCAL'")).scalar() == 1
        conn.execute(text('SET LOCAL search_path TO public'))
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
