"""演示时钟的跨进程共享：偏移量存在文件里，任何进程重建时钟都读到同一个「现在」。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import SharedOffsetClock, build_clock, service_date_of
from app.core.config import get_settings

API = "/api/v1"


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "demo_clock.json"


def clock_at(state_file: Path) -> SharedOffsetClock:
    return SharedOffsetClock(get_settings().business_timezone, state_file)


def test_missing_state_file_reads_as_no_offset(state_file: Path) -> None:
    assert clock_at(state_file).offset == timedelta()


def test_offset_written_by_one_process_is_read_by_another(state_file: Path) -> None:
    tz = ZoneInfo(get_settings().business_timezone)
    # 05:50 仍属前一业务夜，06:10 已经翻到下一夜——用跨 06:00 的偏移验证真的同步。
    before = datetime.now(tz).replace(hour=5, minute=50, second=0, microsecond=0)
    after = before + timedelta(minutes=20)

    writer = clock_at(state_file)
    writer.offset = before - datetime.now(tz)
    assert service_date_of(writer.now()) == service_date_of(before)

    reader = clock_at(state_file)
    reader.offset = after - datetime.now(tz)
    assert service_date_of(reader.now()) == service_date_of(after)
    assert json.loads(state_file.read_text(encoding="utf-8"))["offset_minutes"] == pytest.approx(
        (after - datetime.now(tz)).total_seconds() / 60, abs=1.0
    )


def test_unreadable_state_file_falls_back_to_no_offset(state_file: Path) -> None:
    state_file.write_text("这不是 JSON", encoding="utf-8")
    assert clock_at(state_file).offset == timedelta()

    state_file.write_text(json.dumps({"offset_minutes": "很久以后"}), encoding="utf-8")
    assert clock_at(state_file).offset == timedelta()

    clock_at(state_file).offset = timedelta(minutes=45)
    assert clock_at(state_file).offset == timedelta(minutes=45)


def test_writing_leaves_no_temp_files(tmp_path: Path, state_file: Path) -> None:
    clock_at(state_file).offset = timedelta(minutes=45)
    assert [path.name for path in tmp_path.iterdir()] == ["demo_clock.json"]


def test_build_clock_is_the_shared_one_by_default() -> None:
    first = build_clock()
    assert isinstance(first, SharedOffsetClock)
    first.offset = timedelta(minutes=180)

    second = build_clock()
    assert isinstance(second, SharedOffsetClock)
    assert second.offset == timedelta(minutes=180)
    assert abs(second.now() - first.now()) < timedelta(seconds=2)


def test_demo_endpoint_persisting_offset_also_moves_the_worker_clock(client) -> None:
    response = client.post(f"{API}/demo/clock", json={"offset_minutes": 600})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["offset_minutes"] == 600

    # worker 侧只是再 build_clock() 一次；读到同一个文件就等于读到同一个「现在」。
    worker = build_clock()
    assert worker.offset == timedelta(minutes=600)
    assert abs(worker.now() - datetime.fromisoformat(body["now"])) < timedelta(seconds=2)

    reset = client.post(f"{API}/demo/clock", json={"offset_minutes": 0})
    assert reset.json()["offset_minutes"] == 0
    assert build_clock().offset == timedelta()
