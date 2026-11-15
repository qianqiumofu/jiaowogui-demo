from datetime import datetime


def test_healthz_reports_business_time_and_database(client) -> None:
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["timezone"] == "Asia/Shanghai"
    parsed = datetime.fromisoformat(body["business_time"])
    assert parsed.utcoffset().total_seconds() == 8 * 3600
    assert body["database"] in {"ready", "unconfigured", "unreachable"}
