from __future__ import annotations

import argparse

from .config import Config
from .keyboard_listener import StopController
from .modes import run_free_mode, run_trade_mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Playwright bot")
    parser.add_argument(
        "--mode",
        choices=("free", "trade"),
        help="Run Free Mod (manual login) or Trade Mod (event-driven trades).",
    )
    return parser.parse_args()


def _prompt_for_mode() -> str:
    print("Choose a mode:")
    print("1) Free Mod (open Chrome and keep it open)")
    print("2) Trade Mod (auto-trade from events.ndjson)")
    choice = input("Selection (1/2): ").strip()
    if choice == "1":
        return "free"
    if choice == "2":
        return "trade"
    raise ValueError("Invalid selection; use 1 or 2.")


def main() -> None:
    args = parse_args()
    stop_controller = StopController()
    stop_controller.start()
    config = Config.load()
    try:
        mode = args.mode or _prompt_for_mode()
        if mode == "free":
            run_free_mode(config, stop_controller=stop_controller)
        elif mode == "trade":
            run_trade_mode(config, stop_controller=stop_controller)
    except KeyboardInterrupt:
        stop_controller.request_stop("STOP requested by KeyboardInterrupt")


if __name__ == "__main__":
    main()
