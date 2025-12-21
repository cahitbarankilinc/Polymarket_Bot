from __future__ import annotations

import logging
import time
from datetime import datetime

from .config import Config
from .worker import Worker


def run_scheduler() -> None:
    config = Config.load()
    worker = Worker(config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info("Starting scheduler loop")
    while True:
        now = datetime.now(config.timezone)
        if now.minute % 15 == 0:
            logging.info("Triggering worker at %s", now.isoformat())
            worker.run_once()
            # Prevent rerun in same minute
            time.sleep(60)
        time.sleep(10)

