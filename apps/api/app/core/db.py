from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import ApiError, database_unavailable

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    settings = get_settings()
    if not settings.database_url:
        raise database_unavailable()
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def db_status() -> str:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except ApiError:
        return "unconfigured"
    except SQLAlchemyError:
        return "unreachable"
    return "ready"


def get_session() -> Iterator[Session]:
    global _session_factory
    engine = get_engine()
    assert _session_factory is not None
    try:
        with engine.connect():
            pass
    except SQLAlchemyError as exc:
        raise ApiError(
            503,
            "DATABASE_UNREACHABLE",
            "数据库连接失败，请确认 docker compose 已启动。",
            {"error": str(exc)},
        ) from exc
    assert _session_factory is not None
    with _session_factory() as session:
        yield session
