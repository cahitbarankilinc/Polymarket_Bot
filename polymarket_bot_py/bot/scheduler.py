from __future__ import annotations

import logging
import time
from datetime import datetime

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
                worker.run_once()
                time.sleep(60)
            else:
                time.sleep(10)
        except KeyboardInterrupt:
            stop_controller.request_stop("STOP requested by KeyboardInterrupt")
            break

