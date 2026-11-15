from typing import Annotated

from fastapi import Depends, Header, Request

from app.modules.identity.schemas import SessionContext
from app.modules.identity.service import SessionStore


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def get_session_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> SessionContext:
    token = (authorization or "").removeprefix("Bearer ").strip()
    store = get_session_store(request)
    record, person = store.resolve(token)
    return store.context_for(record, person)


ContextDep = Annotated[SessionContext, Depends(get_session_context)]
