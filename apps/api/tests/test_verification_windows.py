"""核验窗口与二维码时长的纯计算边界（M3 A 侧第一块）。不需要数据库。

锁住基线「边界自检」三条：
- 1／边界 1：00:40 预约，00:09:59 不可核验，00:10:00 与 01:10:00 可以，01:10:01 不可以（R08，端点包含）。
- 边界 2：签发后第 299 秒可用、第 300 秒失效；窗口末尾领码照样完整五分钟，可越过核验窗口上界（R09）。
- 边界 7：06:00 之后旧码即使未过期也只返回夜间授权结束，不获得新一夜资格（R04、基线「统一日期与边界」）。
"""

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.core.clock import service_date_of
from app.core.config import get_settings
from app.modules.verification import windows

REPO_ROOT = Path(__file__).resolve().parents[3]
TZ = ZoneInfo("Asia/Shanghai")
# 业务夜 2026-11-15：门禁时段 11-16 00:00—06:00。
NIGHT = date(2026, 11, 15)
PLANNED = datetime(2026, 11, 16, 0, 40, tzinfo=TZ)


@pytest.fixture(autouse=True)
def baseline_values(monkeypatch):
    """把窗口与码长按基线取值钉死，避免本地 .env 改动让边界用例失真。"""
    monkeypatch.setenv("VERIFICATION_MARGIN_MINUTES", "30")
    monkeypatch.setenv("PASS_CODE_SECONDS", "300")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 16, hour, minute, second, tzinfo=TZ)


def on_day_before(hour: int, minute: int = 0) -> datetime:
    """门禁夜开始前的那个傍晚：11-15 23:xx，仍可核验但不可通行。"""
    return datetime(2026, 11, 15, hour, minute, tzinfo=TZ)


def test_window_endpoints_are_inclusive() -> None:
    window = windows.window_of(PLANNED)
    assert (window.opens_at, window.closes_at) == (at(0, 10), at(1, 10))
    assert window.state_at(at(0, 9, 59)) == windows.VerificationState.NOT_OPEN
    assert window.state_at(at(0, 10)) == windows.VerificationState.OPEN
    assert window.state_at(at(1, 10)) == windows.VerificationState.OPEN
    assert window.state_at(at(1, 10, 1)) == windows.VerificationState.ENDED


def test_verification_may_open_before_midnight() -> None:
    """预约在 00:10 时窗口从 23:40 开始：零点前可核验，但零点前不可通行。"""
    early = datetime(2026, 11, 16, 0, 10, tzinfo=TZ)
    assert windows.state_of(early, now=on_day_before(23, 40)) == windows.VerificationState.OPEN
    assert windows.state_of(early, now=on_day_before(23, 39)) == windows.VerificationState.NOT_OPEN


def test_margin_is_read_from_config(monkeypatch) -> None:
    assert windows.window_of(PLANNED).opens_at == at(0, 10)
    monkeypatch.setenv("VERIFICATION_MARGIN_MINUTES", "45")
    get_settings.cache_clear()
    window = windows.window_of(PLANNED)
    assert (window.opens_at, window.closes_at) == (on_day_before(23, 55), at(1, 25))


def test_code_lives_299_seconds_and_dies_on_300() -> None:
    issued = at(1, 9, 30)
    assert windows.code_expires_at(issued) == at(1, 14, 30)
    assert windows.is_code_live(issued, now=at(1, 14, 29)) is True
    assert windows.is_code_live(issued, now=at(1, 14, 30)) is False


def test_code_issued_at_window_edge_outlives_the_window() -> None:
    """R09：核验窗口已过，五分钟内的旧码仍然有效，不因此要求重新核验。"""
    issued = at(1, 10)
    assert windows.state_of(PLANNED, now=at(1, 12)) == windows.VerificationState.ENDED
    assert windows.is_code_live(issued, now=at(1, 12)) is True


def test_pass_state_covers_the_gate_window() -> None:
    assert windows.pass_state(service_date=NIGHT, issued_at=at(5, 59), now=at(5, 59, 30)) == (
        windows.PassState.ALLOWED
    )
    assert windows.pass_state(service_date=NIGHT, issued_at=at(5, 59), now=at(6, 0)) == (
        windows.PassState.NIGHT_ACCESS_ENDED
    )
    assert windows.pass_state(service_date=NIGHT, issued_at=at(0, 30), now=at(0, 36)) == (
        windows.PassState.CODE_EXPIRED
    )


def test_night_access_end_wins_over_code_expiry() -> None:
    """06:00 后码在 300 秒内仍未过期，但口径只给夜间授权结束，转正常通行流程。"""
    issued = at(5, 59, 50)
    assert windows.is_code_live(issued, now=at(6, 0, 10)) is True
    assert windows.pass_state(service_date=NIGHT, issued_at=issued, now=at(6, 0, 10)) == (
        windows.PassState.NIGHT_ACCESS_ENDED
    )


def test_old_code_gets_no_access_on_the_next_night() -> None:
    """业务日切到 11-16 后，旧码按自身预约夜判定只会拿到 NIGHT_ACCESS_ENDED。"""
    issued = at(5, 50)
    later = at(23, 50)
    assert service_date_of(later) == date(2026, 11, 16)
    assert windows.pass_state(service_date=NIGHT, issued_at=issued, now=later) == (
        windows.PassState.NIGHT_ACCESS_ENDED
    )
    # 同一时刻用新一夜的预约判定仍是「今夜未开始」：00:00 前门禁不放行。
    assert windows.pass_state(service_date=date(2026, 11, 16), issued_at=later, now=later) == (
        windows.PassState.NIGHT_NOT_STARTED
    )


def test_reservation_view_is_server_judged() -> None:
    view = windows.reservation_view(PLANNED, service_date=NIGHT, now=at(0, 20))
    assert view["state"] == "OPEN"
    assert view["margin_minutes"] == 30 and view["code_seconds"] == 300
    assert view["opens_at"].endswith("+08:00")
    assert view["night_access_ends_at"] == "2026-11-16T06:00:00+08:00"
    assert windows.reservation_view(PLANNED, service_date=NIGHT, now=at(2, 0))["state"] == "ENDED"


def test_contract_and_examples_match_the_view() -> None:
    """契约字段、枚举与样例必须跟渲染结果一致，防止改了代码忘了改接口。"""
    spec = yaml.safe_load((REPO_ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    view = windows.reservation_view(PLANNED, service_date=NIGHT, now=at(0, 20))

    assert "verification" in schemas["Reservation"]["required"]
    assert set(schemas["ReservationVerification"]["required"]) == set(view)
    assert set(schemas["VerificationState"]["enum"]) == {state.value for state in windows.VerificationState}

    for name in ("reservation-active-success.json", "reservation-create-risk-notice.json"):
        example = json.loads(
            (REPO_ROOT / "contracts" / "examples" / name).read_text(encoding="utf-8")
        )
        assert set(example["verification"]) == set(view), name


def test_reservation_serialisation_carries_the_view() -> None:
    """不连库也要确认预约响应真的带出 verification：漏传 now 是最容易犯的错。"""
    from types import SimpleNamespace

    from app.modules.reservation.router import _reservation

    res = SimpleNamespace(
        id="resv_synth_0001",
        student_id="stu_synth_0001",
        service_date=NIGHT,
        status="ACTIVE",
        planned_return_at=PLANNED,
        reason="实验室跑数据",
        version=1,
        created_at=at(20, 0),
        updated_at=at(20, 0),
    )
    body = _reservation(res, at(0, 20))
    assert body["verification"] == windows.reservation_view(
        PLANNED, service_date=NIGHT, now=at(0, 20)
    )
