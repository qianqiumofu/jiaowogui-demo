from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

API = "/api/v1"
PASSWORD = "demo1234"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def token_for(client: TestClient, login_name: str) -> str:
    response = client.post(
        f"{API}/auth/mock-login", json={"login_name": login_name, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def jump_clock(client: TestClient, hour: int, minute: int = 0) -> datetime:
    """把演示时钟推进到下一个 HH:MM，让值班与 24:00 边界测试不受真实钟点影响。

    `/demo/clock` 写入的是绝对偏移，因此目标相对未平移的真实时间计算，可连续跳转。
    """
    payload = client.get(f"{API}/demo/clock").json()
    real_now = datetime.fromisoformat(payload["now"]) - timedelta(
        minutes=payload["offset_minutes"]
    )
    target = real_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= real_now:
        target += timedelta(days=1)
    offset = int((target - real_now).total_seconds() // 60)
    response = client.post(f"{API}/demo/clock", json={"offset_minutes": offset})
    assert response.status_code == 200, response.text
    return datetime.fromisoformat(response.json()["now"])
