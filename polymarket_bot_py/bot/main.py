from __future__ import annotations

import argparse

from .scheduler import run_scheduler
from .worker import Worker
from .config import Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Playwright bot")
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.once:
        config = Config.load()
        worker = Worker(config)
        worker.run_once(once=True)
    else:
        run_scheduler()


if __name__ == "__main__":
    main()

