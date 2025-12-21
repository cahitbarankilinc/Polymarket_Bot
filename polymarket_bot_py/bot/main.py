from __future__ import annotations

import argparse

from .config import Config
from .keyboard_listener import StopController
from .scheduler import run_scheduler
from .worker import Worker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Playwright bot")
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stop_controller = StopController()
    stop_controller.start()
    config = Config.load()
    worker = Worker(config, stop_controller=stop_controller)
    try:
        if args.once:
            worker.run_once(once=True)
        else:
            run_scheduler(worker, stop_controller)
    except KeyboardInterrupt:
        stop_controller.request_stop("STOP requested by KeyboardInterrupt")


if __name__ == "__main__":
    main()

