from collections.abc import Iterator

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
