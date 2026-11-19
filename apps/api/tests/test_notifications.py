"""通知投递与模拟收件箱（M1 第 4 条）。全部需要真实 PostgreSQL。

覆盖四件事：
- 渠道按账号来源分流（R18、R19）：统一账户 → 邮件预览，工号账号 → 站内待办。
- 幂等与重放：同一（模板 + 业务夜 + 收件人集合）在任务未消费前只有一条。
- R16：园区不作为风险预警收件人；R15：正文不含超时催办。
- worker 与 API 只共享任务表，投递时刻重新取数（R12 的名单刷新）。
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import service_date_of
from app.modules.notification import templates
from tests.conftest import API, auth, token_for

TZ = ZoneInfo("Asia/Shanghai")
COUNSELOR_ID = "usr_synth_0002"
DORM_ID = "usr_synth_0003"
CAMPUS_ID = "usr_synth_0004"

UNCONFIRMED_NOTE = templates.UNCONFIRMED_NOTE
# R15：任何通知正文都不许出现催办或超时提醒口径。
FORBIDDEN_WORDS = ("超时", "催办", "提醒学生", "已证明未归", "予以处置")

pytestmark = pytest.mark.usefixtures("clean_db")


def now_bj() -> datetime:
    return datetime(2026,11,15,18,0,tzinfo=TZ)


def gate_time(hour: int = 1, minute: int = 30) -> datetime:
    return datetime.combine(service_date_of(now_bj()) + timedelta(days=1), time(hour, minute), TZ)


def create_reservation(client: TestClient, token: str, planned: datetime) -> dict:
    response = client.post(
        f"{API}/reservations",
        json={"planned_return_at": planned.isoformat(), "reason": "实验室跑数据"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def offset_clock(client: TestClient, target: datetime) -> None:
    minutes = int((target - datetime.now(TZ)).total_seconds() // 60)
    assert client.post(f"{API}/demo/clock", json={"offset_minutes": minutes}).status_code == 200


def dispatch(
    client: TestClient,
    campus_token: str,
    *,
    template: str,
    recipients: list[str],
    student_ids: list[str] | None = None,
    service_date: str | None = None,
    deliver_now: bool = True,
) -> tuple[int, dict]:
    payload = {
        "template": template,
        "recipient_user_ids": recipients,
        "student_ids": student_ids,
        "deliver_now": deliver_now,
    }
    if service_date:
        payload["service_date"] = service_date
    response = client.post(
        f"{API}/notification-dispatch", json=payload, headers=auth(campus_token)
    )
    return response.status_code, response.json()


def drain(now: datetime | None = None) -> int:
    """跑一轮 worker：只有 worker 进程会消费任务，API 入口只入队。

    worker 用真实系统时间，API 的演示时钟偏移不跨进程（docs/13），
    所以推进过演示时钟的用例显式传入消费时刻。
    """
    from app.core.clock import OffsetClock, build_clock
    from app.core.config import get_settings
    from app.worker.main import run_once

    clock = (
        build_clock()
        if now is None
        else OffsetClock(get_settings().business_timezone, now - datetime.now(TZ))
    )
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.core.db import get_engine
    from app.db.models import BackgroundJob
    def manual_done():
        with Session(get_engine()) as db:
            return {j.id for j in db.scalars(select(BackgroundJob).where(BackgroundJob.status == "DONE")) if not j.payload.get("reservation_event")}
    before = manual_done()
    run_once(clock, timedelta(seconds=60))
    return len(manual_done() - before)


def inbox(client: TestClient, token: str) -> list[dict]:
    response = client.get(f"{API}/notifications", headers=auth(token))
    assert response.status_code == 200, response.text
    return [r for r in response.json()["items"] if not r["template"].startswith("DORM_")]


def assert_no_reminder_words(body: str) -> None:
    # 「不据此提醒、催办或升级」是 R15 要求的口径说明本身，扫描时先剔除。
    scanned = body.replace(UNCONFIRMED_NOTE, "")
    assert not [word for word in FORBIDDEN_WORDS if word in scanned], scanned


@pytest.fixture()
def campus_token(client: TestClient) -> str:
    return token_for(client, "campus")


@pytest.fixture()
def reservation(client: TestClient, student_token: str, clean_db) -> dict:
    return create_reservation(client, student_token, gate_time())


def test_roster_lands_as_inbox_todo_without_email(
    client, campus_token, reservation
) -> None:
    assert drain() == 0

    status, body = dispatch(
        client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID]
    )
    assert status == 202, body
    assert body["deduped"] is False
    job = body["jobs"][0]
    assert job["job_type"] == "NOTIFICATION_SEND" and job["status"] == "PENDING"
    assert job["business_key"].startswith("NOTIFICATION_SEND:NIGHT_ROSTER:")

    assert drain() == 1

    dorm = token_for(client, "dorm")
    items = inbox(client, dorm)
    assert len(items) == 1
    item = items[0]
    assert item["channel"] == "INBOX" and item["recipient_email"] is None
    assert item["template"] == "NIGHT_ROSTER" and item["status"] == "SENT"
    assert "bldg_a1" in item["subject"]
    assert "2023S0001 张三" in item["body"]
    assert "24:00 是该业务夜首次申请截止" in item["body"]
    assert "本条为站内待办，无需回复。" in item["body"]
    assert_no_reminder_words(item["body"])

    jobs = manual_jobs(client, campus_token)
    assert [(row["id"], row["status"], row["attempts"]) for row in jobs] == [
        (job["id"], "DONE", 1)
    ]
    assert jobs[0]["done_at"] is not None


def test_daily_report_lands_as_email_preview_for_counselor(
    client, campus_token, reservation
) -> None:
    status, body = dispatch(
        client, campus_token, template="DAILY_REPORT", recipients=[COUNSELOR_ID]
    )
    assert status == 202, body
    assert drain() == 1

    counselor = token_for(client, "counselor")
    items = inbox(client, counselor)
    assert len(items) == 1
    item = items[0]
    # 统一身份账户带合成邮箱（R18），所以这条是邮件预览而不是站内待办。
    assert item["channel"] == "EMAIL"
    assert item["recipient_email"] == "T2001@synth.edu.cn"
    assert UNCONFIRMED_NOTE in item["body"]
    assert "本邮件由系统自动生成，请勿回复。" in item["body"]
    assert_no_reminder_words(item["body"])


def test_demo_note_wording_follows_the_recipients_own_scope(
    client, campus_token, reservation
) -> None:
    """演示投递的说明按收件人口径措辞：辅导员听负责关系，宿管听楼栋与代班。"""
    dispatch(client, campus_token, template="DAILY_REPORT", recipients=[COUNSELOR_ID])
    dispatch(client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID])
    assert drain() == 2

    counselor_body = inbox(client, token_for(client, "counselor"))[0]["body"]
    assert "正式版按你负责的学生关系自动生成" in counselor_body
    assert "固定管理楼栋" not in counselor_body

    dorm_body = inbox(client, token_for(client, "dorm"))[0]["body"]
    assert "正式版按你的固定管理楼栋与当日代班范围自动生成" in dorm_body


def test_dispatch_is_idempotent_until_the_job_is_consumed(
    client, campus_token, reservation
) -> None:
    _, first = dispatch(client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID])
    status, second = dispatch(
        client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID]
    )
    assert status == 202
    assert second["deduped"] is True
    assert second["jobs"][0]["id"] == first["jobs"][0]["id"]

    jobs = manual_jobs(client, campus_token)
    assert len(jobs) == 1

    assert drain() == 1
    assert drain() == 0
    assert len(inbox(client, token_for(client, "dorm"))) == 1


def test_redelivery_after_consumption_creates_refreshed_snapshot(
    client, campus_token, reservation
) -> None:
    _, first = dispatch(client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID])
    assert drain() == 1
    _, again = dispatch(client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID])

    assert again["deduped"] is False
    assert again["jobs"][0]["business_key"] == first["jobs"][0]["business_key"] + ":r1"
    assert drain() == 1

    dorm = token_for(client, "dorm")
    keys = {item["job_id"] for item in inbox(client, dorm)}
    assert keys == {first["jobs"][0]["id"], again["jobs"][0]["id"]}


def test_risk_alert_never_targets_campus(client, campus_token, reservation) -> None:
    status, body = dispatch(
        client, campus_token, template="RISK_ALERT", recipients=[CAMPUS_ID]
    )
    assert status == 403
    assert body["code"] == "NOTIFICATION_RECIPIENT_FORBIDDEN"
    assert body["details"]["rule"] == "R16"


@pytest.mark.parametrize(
    ("template", "recipient", "message"),
    [
        ("NIGHT_ROSTER", COUNSELOR_ID, "24:00"),
        ("DAILY_REPORT", DORM_ID, "日报"),
        ("WEEKLY_REPORT", CAMPUS_ID, "周报"),
    ],
)
def test_template_and_recipient_role_must_match(
    client, campus_token, template, recipient, message
) -> None:
    status, body = dispatch(
        client, campus_token, template=template, recipients=[recipient]
    )
    assert status == 422
    assert body["code"] == "NOTIFICATION_TEMPLATE_MISMATCH"
    assert body["details"]["template"] == template


def test_risk_alert_requires_demo_threshold_before_dispatch(
    client, campus_token, reservation
) -> None:
    status, body = dispatch(
        client, campus_token, template="RISK_ALERT", recipients=[COUNSELOR_ID]
    )
    assert status == 422
    assert body["code"] == "VALIDATION_FAILED"
    assert body["details"]["threshold"] == {
        "window_nights": 7,
        "times": 3,
        "consecutive": 3,
    }
    assert manual_jobs(client, campus_token) == []


def test_risk_alert_reaches_counselor_and_dorm_after_three_consecutive_nights(
    client, campus_token, student_token
) -> None:
    moment = now_bj()
    for night_index in range(3):
        moment = now_bj() + timedelta(days=night_index)
        offset_clock(client, moment)
        planned = datetime.combine(
            service_date_of(moment) + timedelta(days=1), time(1, 30), TZ
        )
        create_reservation(client, student_token, planned)

    status, body = dispatch(
        client,
        campus_token,
        template="RISK_ALERT",
        recipients=[COUNSELOR_ID, DORM_ID],
    )
    assert status == 202, body
    assert drain(moment) == 1

    counselor = inbox(client, token_for(client, "counselor"))
    assert len(counselor) == 1
    item = counselor[0]
    assert item["channel"] == "EMAIL"
    assert "第 3 次预约晚归" in item["subject"]
    assert "连续 3 夜" in item["body"]
    assert "不是校规" in item["body"]
    assert "园区不接收本提示" in item["body"]
    assert_no_reminder_words(item["body"])

    dorm = inbox(client, token_for(client, "dorm"))
    assert [(row["template"], row["channel"]) for row in dorm] == [("RISK_ALERT", "INBOX")]


def test_planned_time_comes_from_server_schedule(client, campus_token, reservation) -> None:
    from datetime import timezone

    from app.worker.registry import claim_due_jobs

    _, roster = dispatch(
        client,
        campus_token,
        template="NIGHT_ROSTER",
        recipients=[DORM_ID],
        deliver_now=False,
    )
    _, daily = dispatch(
        client,
        campus_token,
        template="DAILY_REPORT",
        recipients=[COUNSELOR_ID],
        deliver_now=False,
    )
    assert roster["jobs"][0]["planned_at"].endswith("T00:00:00+08:00")
    assert daily["jobs"][0]["planned_at"].endswith("T08:30:00+08:00")
    assert daily["jobs"][0]["planned_at"][:10] == roster["jobs"][0]["planned_at"][:10]

    drain()  # 先排空独立的预约通过事件；其计划时刻不受名单汇总影响。
    # 队列按服务端算出的计划时刻放行，早于 24:00 不领取名单。
    planned = datetime.fromisoformat(roster["jobs"][0]["planned_at"]).astimezone(timezone.utc)
    assert claim_due_jobs(planned - timedelta(minutes=1), timedelta(seconds=60)) == []
    claimed = claim_due_jobs(planned + timedelta(minutes=1), timedelta(seconds=60))
    assert [row["business_key"] for row in claimed] == [roster["jobs"][0]["business_key"]]


def test_inbox_reads_own_items_only_and_mark_read_is_idempotent(
    client, campus_token, reservation
) -> None:
    dispatch(client, campus_token, template="NIGHT_ROSTER", recipients=[DORM_ID])
    dispatch(client, campus_token, template="DAILY_REPORT", recipients=[COUNSELOR_ID])
    assert drain() == 2

    dorm_item = inbox(client, token_for(client, "dorm"))[0]
    counselor_token = token_for(client, "counselor")

    stolen = client.get(
        f"{API}/notifications/{dorm_item['id']}", headers=auth(counselor_token)
    )
    assert stolen.status_code == 404
    assert stolen.json()["code"] == "NOTIFICATION_NOT_FOUND"

    mine = inbox(client, counselor_token)[0]
    read = client.post(f"{API}/notifications/{mine['id']}/read", headers=auth(counselor_token))
    assert read.status_code == 200
    assert read.json()["status"] == "READ"
    first_read_at = read.json()["read_at"]

    again = client.post(f"{API}/notifications/{mine['id']}/read", headers=auth(counselor_token))
    assert again.json()["read_at"] == first_read_at

    only_unread = client.get(
        f"{API}/notifications", params={"unread_only": True}, headers=auth(counselor_token)
    ).json()["items"]
    assert [row["id"] for row in only_unread] == []


@pytest.mark.parametrize("login", ["student"])
def test_inbox_read_denied_without_action(client, login, reservation) -> None:
    response = client.get(f"{API}/notifications", headers=auth(token_for(client, login)))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"
    assert response.json()["details"]["action"] == "notification:read"


@pytest.mark.parametrize("login", ["counselor", "student"])
def test_dispatch_denied_outside_campus(client, login, reservation) -> None:
    response = client.post(
        f"{API}/notification-dispatch",
        json={"template": "NIGHT_ROSTER", "recipient_user_ids": [DORM_ID]},
        headers=auth(token_for(client, login)),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"
    assert response.json()["details"]["action"] == "notification:dispatch"


@pytest.mark.parametrize("login", ["dorm", "counselor"])
def test_job_list_denied_outside_campus(client, login, reservation) -> None:
    response = client.get(f"{API}/notification-jobs", headers=auth(token_for(client, login)))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ACTION"
    assert response.json()["details"]["action"] == "notification_job:read"


def test_weekly_report_summarises_seven_business_nights(
    client, campus_token, student_token
) -> None:
    moment = now_bj()
    for night_index in (0, 3):
        moment = now_bj() + timedelta(days=night_index)
        offset_clock(client, moment)
        planned = datetime.combine(
            service_date_of(moment) + timedelta(days=1), time(1, 30), TZ
        )
        create_reservation(client, student_token, planned)

    latest_night = service_date_of(moment)
    status, body = dispatch(
        client,
        campus_token,
        template="WEEKLY_REPORT",
        recipients=[COUNSELOR_ID],
        service_date=latest_night.isoformat(),
    )
    assert status == 202, body
    assert drain(moment) == 1

    item = inbox(client, token_for(client, "counselor"))[0]
    assert item["template"] == "WEEKLY_REPORT"
    assert "共提交晚归预约 2 条" in item["body"]
    assert "预约 1 条｜未确认 1 条" in item["body"]
    assert "周报按你的订阅发送" in item["body"]
    assert_no_reminder_words(item["body"])


def test_disabled_staff_recipient_is_skipped_instead_of_retrying_forever(
    client, campus_token, reservation
) -> None:
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from app.core.db import get_engine
    from app.db.models import Notification

    campus = token_for(client, "campus")
    created = client.post(
        f"{API}/staff-accounts",
        json={
            "login_name": "dorm_r9",
            "display_name": "孙宿管（bldg_a9）",
            "building_ids": ["bldg_a9"],
        },
        headers=auth(campus),
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["account"]["id"]

    status, body = dispatch(
        client, campus_token, template="NIGHT_ROSTER", recipients=[account_id]
    )
    assert status == 202, body
    assert client.post(f"{API}/staff-accounts/{account_id}/disable", headers=auth(campus)).status_code == 200

    assert drain() == 1

    session = sessionmaker(get_engine())()
    try:
        rows = session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.recipient_user_id == account_id
            )
        )
    finally:
        session.close()
    jobs = manual_jobs(client, campus)
    assert rows == 0
    assert [row["status"] for row in jobs] == ["DONE"]


def manual_jobs(client, token):
    response = client.get(f"{API}/notification-jobs", headers=auth(token))
    assert response.status_code == 200
    return [j for j in response.json()["items"] if not j["template"].startswith("DORM_")]
