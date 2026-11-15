from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import APIRouter, FastAPI, Request

from app.api.router import api_router
from app.core.clock import build_clock
from app.core.config import get_settings
from app.core.db import db_status
from app.core.errors import install_error_handlers
from app.modules.identity.service import SessionStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    clock = build_clock()
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_store = SessionStore(
        clock, timedelta(minutes=settings.session_ttl_minutes)
    )
    yield
    app.state.session_store.clear()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.0.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    health = APIRouter(tags=["demo"])

    @health.get("/healthz")
    def healthz(request: Request) -> dict:
        return {
            "status": "ok",
            "timezone": request.app.state.settings.business_timezone,
            "business_time": request.app.state.clock.now().isoformat(),
            "database": db_status(),
        }

    app.include_router(health)
    return app


app = create_app()
