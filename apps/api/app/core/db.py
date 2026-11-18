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
        # 数据库宕机时 libpq 默认无限等待，探活与请求会挂死；限定 5 秒快速失败。
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
            connect_args={"connect_timeout": 5},
        )
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
    engine = get_engine()
    assert _session_factory is not None
    with _session_factory() as session:
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise ApiError(
                503,
                "DATABASE_UNREACHABLE",
                "数据库连接失败，请确认 docker compose 已启动。",
                {"error": str(exc)},
            ) from exc
        yield session
