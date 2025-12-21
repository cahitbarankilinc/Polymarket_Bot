from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from .config import Config
from .selectors import TradePage
from .state import BotState
from .utils import bucket_key, configure_logging, safe_float_from_text, setup_run_directory


@dataclass
class WorkerResult:
    ran: bool
    skipped_reason: Optional[str] = None


class Worker:
    def __init__(self, config: Config):
        self.config = config
        self.state = BotState.load(config.state_path)
        self.run_dir: Optional[Path] = None

    def should_skip(self, now: datetime, once: bool) -> Optional[str]:
        pause_until = self.state.pause_until()
        if pause_until and pause_until > now:
            return f"Paused until {pause_until.isoformat()}"
        key = bucket_key(now)
        if not once and self.state.last_bucket_key == key:
            return f"Bucket {key} already processed"
        return None

    def run_once(self, *, once: bool = False) -> WorkerResult:
        now = datetime.now(self.config.timezone)
        run_dir, log_path = setup_run_directory(self.config.runs_root, self.config.timezone)
        self.run_dir = run_dir
        configure_logging(log_path)
        logging.info("Run directory: %s", run_dir)
        reason = self.should_skip(now, once)
        if reason:
            logging.info("Skipping run: %s", reason)
            return WorkerResult(ran=False, skipped_reason=reason)

        try:
            self._execute(now)
            self.state.last_bucket_key = bucket_key(now)
            self.state.save(self.config.state_path)
            logging.info("Run completed")
            return WorkerResult(ran=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.exception("Run failed: %s", exc)
            return WorkerResult(ran=False, skipped_reason=str(exc))

    def _execute(self, now: datetime) -> None:
        with sync_playwright() as playwright:
            self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
            browser = playwright.chromium.launch_persistent_context(
                str(self.config.user_data_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
                viewport={"width": 1280, "height": 900},
            )
            browser.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = browser.new_page()
            trade_page = TradePage(page)
            error_happened = False
            try:
                self._navigate_and_prepare(trade_page)
                if self._should_pause(trade_page, now):
                    logging.info("Pause condition met; skipping trade")
                    return
                self._fill_form(trade_page)
                if not self.config.dry_run:
                    button = trade_page.trade_button()
                    button.click()
                    logging.info("Trade button clicked")
                else:
                    logging.info("DRY_RUN enabled; not clicking trade button")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                error_happened = True
                logging.exception("Workflow error: %s", exc)
                raise
            finally:
                self._capture_artifacts(page, browser, error=error_happened)
                browser.close()

    def _navigate_and_prepare(self, trade_page: TradePage) -> None:
        page = trade_page.page
        page.goto(self.config.home_15m_url, wait_until="domcontentloaded")
        logging.info("Navigated to home page")
        trade_page.open_market_card(self.config.card_text)
        page.wait_for_timeout(2000)
        logging.info("Opened market card")
        trade_page.ensure_limit_mode()
        logging.info("Limit mode ensured")
        trade_page.select_side(self.config.side)
        logging.info("Selected side %s", self.config.side)

    def _should_pause(self, trade_page: TradePage, now: datetime) -> bool:
        try:
            beat_text, current_text = trade_page.prices()
            beat_price = safe_float_from_text(beat_text)
            current_price = safe_float_from_text(current_text)
            logging.info("Price to beat: %s | Current price: %s", beat_price, current_price)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("Price read failed (%s); continuing without pause logic", exc)
            return False

        diff = abs(current_price - beat_price)
        if diff > self.config.diff_threshold_usd:
            pause_until = now + timedelta(minutes=self.config.pause_minutes)
            self.state.pause_until_iso = pause_until.isoformat()
            self.state.save(self.config.state_path)
            logging.warning(
                "Price diff %.2f exceeds threshold %.2f; pausing until %s",
                diff,
                self.config.diff_threshold_usd,
                pause_until.isoformat(),
            )
            return True
        self.state.pause_until_iso = None
        self.state.save(self.config.state_path)
        return False

    def _fill_form(self, trade_page: TradePage) -> None:
        trade_page.fill_limit_price(self.config.limit_price_cents)
        logging.info("Filled limit price with %s", self.config.limit_price_cents)
        trade_page.fill_shares(self.config.shares)
        logging.info("Filled shares with %s", self.config.shares)

    def _capture_artifacts(self, page, browser, *, error: bool = False) -> None:
        if not self.run_dir:
            return
        list_path = self.run_dir / "screenshot_list.png"
        event_path = self.run_dir / "screenshot_event.png"
        error_path = self.run_dir / "error.png"
        trace_path = self.run_dir / "trace.zip"
        try:
            page.screenshot(path=list_path)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to capture list screenshot")
        try:
            page.screenshot(path=event_path, full_page=True)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to capture event screenshot")
        if error:
            try:
                page.screenshot(path=error_path, full_page=True)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Failed to capture error screenshot")
        try:
            browser.tracing.stop(path=str(trace_path))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to save trace")

