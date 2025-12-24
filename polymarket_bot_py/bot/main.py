from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from .config import Config
from .keyboard_listener import StopController
from .scheduler import run_scheduler
from .worker import Worker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Playwright bot")
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit")
    parser.add_argument(
        "--mode",
        choices=("scheduler", "free", "trade"),
        default="scheduler",
        help="Run mode: scheduler (default), free (open browser), trade (use events.ndjson)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stop_controller = StopController()
    stop_controller.start()
    config = Config.load()
    worker = Worker(config, stop_controller=stop_controller)
    tracker_process: subprocess.Popen[str] | None = None
    try:
        if args.mode == "free":
            if args.once:
                logging.warning("--once ignored in free mode")
            worker.run_free_mode()
        elif args.mode == "trade":
            if args.once:
                logging.warning("--once ignored in trade mode")
            tracker_process = _start_tracker(config)
            worker.run_trade_mode()
        else:
            if args.once:
                worker.run_once(once=True)
            else:
                run_scheduler(worker, stop_controller)
    except KeyboardInterrupt:
        stop_controller.request_stop("STOP requested by KeyboardInterrupt")
    finally:
        _stop_tracker(tracker_process)


def _start_tracker(config: Config) -> subprocess.Popen[str]:
    if not config.tracker_script.exists():
        raise FileNotFoundError(f"Tracker script not found: {config.tracker_script}")
    command = [
        sys.executable,
        str(config.tracker_script),
        "--minutes",
        "0",
        "--output-dir",
        str(config.tracker_output_dir),
    ]
    logging.info("Starting tracker: %s", " ".join(command))
    return subprocess.Popen(command)


def _stop_tracker(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        logging.info("Stopping tracker process")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logging.warning("Tracker process did not stop; killing")
            process.kill()


if __name__ == "__main__":
    main()
