"""唯一的调度注册处：只允许 worker 进程领取任务，API 进程不得起定时器。

任务表语义（迁移由 B 发布）：background_jobs(job_type, business_key UNIQUE,
planned_at, status, lease_until, attempts, last_error, done_at)。
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import timedelta

from app.core.clock import Clock
from app.worker.registry import HANDLERS, claim_due_jobs, mark_failed, mark_succeeded

LOGGER = logging.getLogger("jiaowogui.worker")


def run_once(clock: Clock, lease: timedelta) -> int:
    handled = 0
    for job in claim_due_jobs(clock.now(), lease):
        handler = HANDLERS.get(job["job_type"])
        if handler is None:
            mark_failed(job["id"], f"no handler for {job['job_type']}", clock.now())
            continue
        try:
            handler(job)
            mark_succeeded(job["id"], clock.now())
        except Exception as exc:  # noqa: BLE001 - 任务失败必须落库重试，不能让 worker 退出
            LOGGER.exception("job %s failed", job["id"])
            mark_failed(job["id"], str(exc), clock.now())
        handled += 1
    return handled


def main() -> None:
    parser = argparse.ArgumentParser(description="jiaowogui worker")
    parser.add_argument("--once", action="store_true", help="扫描一轮后退出，用于联调")
    parser.add_argument("--interval", type=int, default=30, help="轮询间隔秒")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from app.core.clock import build_clock
    from app.core.errors import ApiError

    clock = build_clock()
    if not args.once:
        LOGGER.info("worker loop start, handlers=%s", sorted(HANDLERS))
        while True:
            try:
                run_once(clock, timedelta(seconds=60))
            except ApiError as exc:
                LOGGER.error("scan skipped: %s (set DATABASE_URL in apps/api/.env and start postgres)", exc.code)
            time.sleep(args.interval)
        return

    try:
        LOGGER.info("single pass handled=%d", run_once(clock, timedelta(seconds=60)))
    except ApiError as exc:
        LOGGER.error("scan skipped: %s (set DATABASE_URL in apps/api/.env and start postgres)", exc.code)


if __name__ == "__main__":
    main()
