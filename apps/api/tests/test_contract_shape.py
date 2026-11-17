"""统一错误信封、时区口径与演示时钟。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.clock import service_date_of
from tests.conftest import API, auth, token_for


def test_error_envelope_fields(client) -> None:
    token = token_for(client, "student")
    response = client.get(
        f"{API}/authz/scope-check", headers=auth(token), params={"action": "unknown:action"}
    )
    assert response.status_code == 403
    body = response.json()
    assert set(body) == {"code", "message", "request_id", "details"}
    assert body["request_id"]


def test_service_date_rolls_over_at_six() -> None:
    from app.core.clock import service_date_of

    tz = ZoneInfo("Asia/Shanghai")
    assert service_date_of(datetime(2026, 11, 15, 5, 59, tzinfo=tz)).isoformat() == "2026-11-14"
    assert service_date_of(datetime(2026, 11, 15, 6, 0, tzinfo=tz)).isoformat() == "2026-11-15"


def test_demo_clock_crosses_midnight(client) -> None:
    response = client.post(f"{API}/demo/clock", json={"offset_minutes": 120})
    assert response.status_code == 200
    assert response.json()["offset_minutes"] == 120
    state = client.get(f"{API}/demo/clock").json()
    assert state["offset_minutes"] == 120
    # 业务夜由服务端给出，客户端不自行推算；与 R04 的 06:00 归属规则一致。
    assert state["service_date"] == service_date_of(
        datetime.fromisoformat(state["now"])
    ).isoformat()
