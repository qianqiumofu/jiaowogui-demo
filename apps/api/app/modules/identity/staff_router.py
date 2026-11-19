"""宿管工号账号的园区管理入口（A 主责，R19）。

权限：`staff_account:*` 仅园区角色；宿管、辅导员和学生都没有账号入口。
初始口令只在创建与重置响应里返回一次，列表与详情一律不带口令。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.clock import business_iso
from app.core.db import get_session
from app.modules.authorization.dependencies import require
from app.modules.identity import staff_accounts
from app.modules.identity.schemas import SessionContext, StaffAccountCreate, StaffAccountPatch
from app.modules.identity.service import SessionStore

router = APIRouter(prefix="/staff-accounts", tags=["identity"])

ReadDep = Annotated[SessionContext, Depends(require("staff_account:read"))]
CreateDep = Annotated[SessionContext, Depends(require("staff_account:create"))]
UpdateDep = Annotated[SessionContext, Depends(require("staff_account:update"))]
ResetDep = Annotated[SessionContext, Depends(require("staff_account:reset"))]
DisableDep = Annotated[SessionContext, Depends(require("staff_account:disable"))]
SessionDep = Annotated[Session, Depends(get_session)]


def _account(account) -> dict:
    return {
        "id": account.user_id,
        "login_name": account.login_name,
        "display_name": account.display_name,
        "building_ids": list(account.building_ids),
        "status": account.status,
        "created_at": business_iso(account.created_at),
        "disabled_at": business_iso(account.disabled_at) if account.disabled_at else None,
    }


def _store(request: Request) -> SessionStore:
    return request.app.state.session_store


@router.get("")
def list_staff_accounts(guarded: ReadDep, db: SessionDep) -> dict:
    return {"items": [_account(a) for a in staff_accounts.list_accounts(db)], "next_cursor": None}


@router.post("", status_code=201)
def create_staff_account(
    guarded: CreateDep, db: SessionDep, payload: StaffAccountCreate
) -> dict:
    account, initial_password = staff_accounts.create_account(
        db,
        login_name=payload.login_name,
        display_name=payload.display_name,
        building_ids=payload.building_ids,
    )
    return {"account": _account(account), "initial_password": initial_password}


@router.patch("/{staff_account_id}")
def update_staff_account(
    staff_account_id: str,
    guarded: UpdateDep,
    db: SessionDep,
    payload: StaffAccountPatch,
) -> dict:
    account = staff_accounts.update_account(
        db,
        staff_account_id,
        display_name=payload.display_name,
        building_ids=payload.building_ids,
    )
    return _account(account)


@router.post("/{staff_account_id}/reset-password")
def reset_staff_password(
    staff_account_id: str, guarded: ResetDep, db: SessionDep, request: Request
) -> dict:
    account, password = staff_accounts.reset_password(db, staff_account_id)
    _store(request).drop_user(account.user_id)
    return {"account": _account(account), "initial_password": password}


@router.post("/{staff_account_id}/disable")
def disable_staff_account(
    staff_account_id: str, guarded: DisableDep, db: SessionDep, request: Request
) -> dict:
    account = staff_accounts.disable(db, request.app.state.clock, staff_account_id)
    _store(request).drop_user(account.user_id)
    return _account(account)
