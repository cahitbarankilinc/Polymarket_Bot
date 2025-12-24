from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, sync_playwright

from .config import Config
from .keyboard_listener import StopController
from .selectors import TradePage
from .utils import configure_logging, setup_run_directory


@dataclass
class BrowserSession:
    playwright: object
    context: object
    page: Page


@dataclass
class TrackerProcess:
    process: subprocess.Popen
    log_handle: object


class BrowserManager:
    def __init__(self, config: Config):
        self.config = config
        self._playwright = None
        self._context = None
        self._page: Optional[Page] = None

    def launch(self) -> BrowserSession:
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._context is None:
            self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.config.user_data_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
                viewport={"width": 1280, "height": 900},
            )
            self._context.set_default_timeout(0)
            self._context.set_default_navigation_timeout(0)
        if self._page is None:
            self._page = self._context.new_page()
            self._page.set_default_timeout(0)
            self._page.set_default_navigation_timeout(0)
        return BrowserSession(self._playwright, self._context, self._page)


def run_free_mode(config: Config, stop_controller: Optional[StopController] = None) -> None:
    run_dir, log_path = setup_run_directory(config.runs_root, config.timezone)
    configure_logging(log_path)
    logging.info("Free mode run directory: %s", run_dir)
    browser = BrowserManager(config).launch()
    browser.page.goto(config.home_15m_url, wait_until="domcontentloaded")
    logging.info("Chrome launched in Free Mode. Close manually when done.")
    _idle_until_stop(stop_controller)


def run_trade_mode(config: Config, stop_controller: Optional[StopController] = None) -> None:
    run_dir, log_path = setup_run_directory(config.runs_root, config.timezone)
    configure_logging(log_path)
    logging.info("Trade mode run directory: %s", run_dir)
    tracker_process = _start_tracker_process(config.tracker_script_path, run_dir)
    browser = BrowserManager(config).launch()
    logging.info("Trade mode started. Listening for events at %s", config.events_ndjson_path)
    try:
        _trade_loop(browser.page, config, stop_controller)
    finally:
        if tracker_process:
            try:
                tracker_process.process.terminate()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Tracker process terminate failed")
            try:
                tracker_process.log_handle.close()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Tracker log handle close failed")
        logging.info("Trade loop stopped. Chrome remains open.")
        _idle_until_stop(stop_controller)


def _idle_until_stop(stop_controller: Optional[StopController]) -> None:
    while True:
        if stop_controller and stop_controller.stop_requested():
            logging.info("Stop requested; exiting without closing Chrome")
            break
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            if stop_controller:
                stop_controller.request_stop("STOP requested by KeyboardInterrupt during idle")
            break


def _start_tracker_process(script_path: Path, run_dir: Path) -> Optional[TrackerProcess]:
    if not script_path.exists():
        logging.error("Tracker script not found at %s", script_path)
        return None
    tracker_log = run_dir / "tracker.log"
    tracker_handle = tracker_log.open("a", encoding="utf-8")
    logging.info("Starting tracker script: %s", script_path)
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=tracker_handle,
        stderr=tracker_handle,
        cwd=str(script_path.parent),
    )
    return TrackerProcess(process=process, log_handle=tracker_handle)


def _trade_loop(page: Page, config: Config, stop_controller: Optional[StopController]) -> None:
    while True:
        if stop_controller and stop_controller.stop_requested():
            logging.info("Stop requested; exiting trade loop")
            break
        _sleep_until_next_minute(config.timezone, stop_controller)
        if stop_controller and stop_controller.stop_requested():
            logging.info("Stop requested before processing next event")
            break
        event = _read_latest_event(config.events_ndjson_path)
        if not event:
            logging.warning("No event data found; skipping this minute")
            continue
        outcome = _normalize_outcome(event.get("outcome") or event.get("Outcome"))
        if outcome not in {"UP", "DOWN"}:
            logging.warning("Unsupported outcome '%s'; stopping trade loop", outcome)
            break
        market = event.get("Market") or event.get("market")
        if not market:
            logging.warning("Event missing Market field; skipping this minute")
            continue
        price = event.get("price") or event.get("Price")
        size = event.get("size") or event.get("Size")
        if price is None or size is None:
            logging.warning("Event missing price/size fields; skipping this minute")
            continue
        limit_price_cents = float(price) * 100
        shares = float(size)
        _execute_trade(page, config, market, outcome, limit_price_cents, shares, stop_controller)


def _sleep_until_next_minute(timezone, stop_controller: Optional[StopController]) -> None:
    now = datetime.now(timezone)
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    while datetime.now(timezone) < next_minute:
        if stop_controller and stop_controller.stop_requested():
            return
        time.sleep(0.25)


def _read_latest_event(path: Path) -> Optional[dict]:
    if not path.exists():
        logging.warning("Events file not found at %s", path)
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    return json.loads(stripped)
    except json.JSONDecodeError as exc:
        logging.warning("Failed to decode JSON from %s: %s", path, exc)
        return None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.warning("Failed to read events file %s: %s", path, exc)
        return None
    return None


def _normalize_outcome(outcome: Optional[str]) -> str:
    if not outcome:
        return ""
    return outcome.strip().upper()


def _execute_trade(
    page: Page,
    config: Config,
    market: str,
    outcome: str,
    limit_price_cents: float,
    shares: float,
    stop_controller: Optional[StopController],
) -> None:
    if stop_controller and stop_controller.stop_requested():
        logging.info("Stop requested before trade execution")
        return
    url = f"https://polymarket.com/event/{market}"
    logging.info("Navigating to %s", url)
    page.goto(url, wait_until="domcontentloaded")
    trade_page = TradePage(page)
    trade_page.ensure_widget_ready()
    try:
        trade_page.ensure_limit_mode()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.warning("ensure_limit_mode failed but continuing: %s", exc)
    trade_page.select_side(outcome)
    logging.info("Selected side %s", outcome)
    trade_page.fill_limit_price(limit_price_cents)
    logging.info("Filled limit price with %s", limit_price_cents)
    trade_page.fill_shares(shares)
    logging.info("Filled shares with %s", shares)
    if stop_controller and stop_controller.stop_requested():
        logging.info("Stop requested before trade submit")
        return
    if not config.dry_run:
        trade_page.trade_button().click()
        logging.info("Trade button clicked")
    else:
        logging.info("DRY_RUN enabled; not clicking trade button")
