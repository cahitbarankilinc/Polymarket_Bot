from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from .keyboard_listener import StopController
from .worker import Worker


def run_scheduler(worker: Worker, stop_controller: StopController) -> None:
    config = worker.config
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info("Starting scheduler loop")

    while not stop_controller.stop_requested():
        try:
            now = datetime.now(config.timezone)
            if now.minute % 15 == 0:
                logging.info("Triggering worker at %s", now.isoformat())
                result = worker.run_once()
                next_bucket_time = _next_bucket_start(now)
                if result.ran:
                    logging.info(
                        "Run completed; sleeping until next bucket: %s", next_bucket_time.isoformat()
                    )
                else:
                    logging.info(
                        "Run completed (skipped: %s); sleeping until next bucket: %s",
                        result.skipped_reason,
                        next_bucket_time.isoformat(),
                    )
                _sleep_until(next_bucket_time, config.timezone, stop_controller)
                if not stop_controller.stop_requested():
                    logging.info("Woke up; next run starting...")
            else:
                next_bucket_time = _next_bucket_start(now)
                logging.info("Waiting until next bucket: %s", next_bucket_time.isoformat())
                _sleep_until(next_bucket_time, config.timezone, stop_controller)
                if not stop_controller.stop_requested():
                    logging.info("Woke up; next run starting...")
        except KeyboardInterrupt:
            stop_controller.request_stop("STOP requested by KeyboardInterrupt")
            break


def _next_bucket_start(now: datetime) -> datetime:
    minute_block = (now.minute // 15) * 15
    bucket_start = now.replace(minute=minute_block, second=0, microsecond=0)
    next_start = bucket_start + timedelta(minutes=15)
    if now.minute % 15 == 0 and now.second == 0 and now.microsecond == 0:
        return next_start
    if now >= next_start:
        return next_start + timedelta(minutes=15)
    return next_start


def _sleep_until(target: datetime, tz, stop_controller: StopController) -> None:
    while not stop_controller.stop_requested():
        now = datetime.now(tz)
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            break
        sleep_for = min(remaining, 30)
        time.sleep(sleep_for)

