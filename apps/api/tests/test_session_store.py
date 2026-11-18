"""进程内会话表的过期清理：不依赖数据库。"""

from datetime import timedelta

from app.core.clock import OffsetClock
from app.core.config import get_settings
from app.modules.identity.service import SessionStore


def test_expired_sessions_purged_on_new_login() -> None:
    clock = OffsetClock(get_settings().business_timezone)
    store = SessionStore(clock, timedelta(minutes=30))
    password = get_settings().demo_login_password

    first = store.login("student", password)
    clock.offset += timedelta(minutes=31)
    second = store.login("student", password)

    assert first.token not in store._by_token
    assert second.token in store._by_token


def test_unexpired_sessions_survive_purge() -> None:
    clock = OffsetClock(get_settings().business_timezone)
    store = SessionStore(clock, timedelta(minutes=30))
    password = get_settings().demo_login_password

    first = store.login("student", password)
    second = store.login("dorm", password)

    assert first.token in store._by_token
    assert second.token in store._by_token