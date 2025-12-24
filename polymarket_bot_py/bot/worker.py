from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page, sync_playwright

from .config import Config
from .keyboard_listener import StopController
from .selectors import TradePage
from .state import BotState
from .utils import bucket_key, configure_logging, safe_float_from_text, setup_run_directory


@dataclass
class WorkerResult:
    ran: bool
    skipped_reason: Optional[str] = None


class Worker:
    def __init__(self, config: Config, stop_controller: Optional[StopController] = None):
        self.config = config
        self.state = BotState.load(config.state_path)
        self.run_dir: Optional[Path] = None
        self.stop_controller = stop_controller
        self._playwright = None
        self._browser_context = None
        self._page: Optional[Page] = None

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
        if self._stop_requested():
            logging.info("Skipping run: stop requested")
            return WorkerResult(ran=False, skipped_reason="Stop requested")
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
        finally:
            if once and not self.config.auto_close_browser and self._browser_context:
                self._wait_for_manual_close()

    def run_free_mode(self) -> None:
        run_dir, log_path = setup_run_directory(self.config.runs_root, self.config.timezone)
        self.run_dir = run_dir
        configure_logging(log_path)
        logging.info("Starting free mode (browser stays open)")
        page = self._ensure_page(self._ensure_browser(self._ensure_playwright()))
        page.goto(self.config.free_mode_url, wait_until="domcontentloaded")
        logging.info("Opened free mode URL: %s", self.config.free_mode_url)
        self._wait_for_manual_close()

    def run_trade_mode(self) -> None:
        run_dir, log_path = setup_run_directory(self.config.runs_root, self.config.timezone)
        self.run_dir = run_dir
        configure_logging(log_path)
        logging.info("Starting trade mode loop")
        page = self._ensure_page(self._ensure_browser(self._ensure_playwright()))

        while not self._stop_requested():
            try:
                event_data = self._read_next_event(self.config.events_path)
                if event_data is None:
                    logging.info("No event found in %s", self.config.events_path)
                else:
                    event, event_key = event_data
                    outcome = (event.get("outcome") or "").strip().upper()
                    if outcome not in {"UP", "DOWN"}:
                        logging.warning(
                            "Unexpected outcome '%s' (event: %s); skipping this event",
                            outcome,
                            event.get("market"),
                        )
                        self._mark_event_processed(event_key)
                        page = self._refresh_trade_tab(page)
                        continue
                    self._execute_event_trade(page, event, outcome)
                    self._mark_event_processed(event_key)
                    page = self._refresh_trade_tab(page)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.exception("Trade mode error: %s", exc)

            self._sleep_until_next_minute()

        logging.info("Stop requested; exiting trade mode without closing browser")

    def _execute(self, now: datetime) -> None:
        playwright = self._ensure_playwright()
        browser = self._ensure_browser(playwright)
        page = self._ensure_page(browser)
        self._start_tracing(browser)
        trade_page = TradePage(page)
        error_happened = False
        try:
            self._navigate_and_prepare(trade_page)
            if self._stop_requested():
                logging.info("Stop requested before pause check; aborting run")
                return
            if self._should_pause(trade_page, now):
                logging.info("Pause condition met; skipping trade")
                return
            if self._stop_requested():
                logging.info("Stop requested before fill; aborting run")
                return
            self._fill_form(trade_page)
            if self._stop_requested():
                logging.info("Stop requested before submit; aborting run")
                return
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
            if self.config.auto_close_browser and not self._stop_requested():
                try:
                    browser.close()
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.warning("Browser close failed")
                try:
                    playwright.stop()
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.warning("Playwright stop failed")
            else:
                logging.info("Leaving browser/context open (AUTO_CLOSE_BROWSER=%s)", self.config.auto_close_browser)

    def _wait_for_manual_close(self) -> None:
        logging.info(
            "AUTO_CLOSE_BROWSER disabled; keeping browser open. Press ESC or Ctrl+C to exit without closing it."
        )
        while True:
            try:
                if self._stop_requested():
                    logging.info("Stop requested; exiting without closing browser")
                    break
                time.sleep(1)
            except KeyboardInterrupt:
                if self.stop_controller:
                    self.stop_controller.request_stop(
                        "STOP requested by KeyboardInterrupt during manual browser hold"
                    )
                break

    def _navigate_and_prepare(self, trade_page: TradePage) -> None:
        page = trade_page.page
        page.set_default_timeout(0)
        page.set_default_navigation_timeout(0)
        page.goto(self.config.home_15m_url, wait_until="domcontentloaded")
        logging.info("Navigated to home page")
        trade_page.open_market_card(self.config.card_text)
        page.wait_for_timeout(2000)
        logging.info("Opened market card")
        trade_page.ensure_widget_ready()
        try:
            trade_page.ensure_limit_mode()
            logging.info("Limit mode check completed")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("ensure_limit_mode failed but continuing: %s", exc)
        trade_page.select_side(self.config.side)
        logging.info("Selected side %s", self.config.side)

    def _execute_event_trade(self, page: Page, event: dict[str, Any], outcome: str) -> None:
        market = event.get("market")
        if not market:
            logging.warning("Event missing market; skipping trade")
            return
        price = event.get("price")
        size = event.get("size")
        if price is None or size is None:
            logging.warning("Event missing price/size; skipping trade for market %s", market)
            return
        try:
            limit_price_cents = round(float(price) * 100, 4)
            shares = float(size)
        except (TypeError, ValueError):
            logging.warning("Event price/size not numeric; skipping trade for market %s", market)
            return

        url = f"{self.config.trade_event_url_base}{market}"
        page.goto(url, wait_until="domcontentloaded")
        logging.info("Opened event URL: %s", url)
        trade_page = TradePage(page)
        trade_page.ensure_widget_ready()
        try:
            trade_page.ensure_limit_mode()
            logging.info("Limit mode check completed")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning("ensure_limit_mode failed but continuing: %s", exc)
        trade_page.select_side(outcome)
        logging.info("Selected side %s", outcome)
        trade_page.fill_limit_price(limit_price_cents)
        logging.info("Filled limit price with %s", limit_price_cents)
        trade_page.fill_shares(shares)
        logging.info("Filled shares with %s", shares)
        if not self.config.dry_run:
            button = trade_page.trade_button()
            button.click()
            logging.info("Trade button clicked")
        else:
            logging.info("DRY_RUN enabled; not clicking trade button")

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

    def _ensure_playwright(self):
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        return self._playwright

    def _ensure_browser(self, playwright):
        if self._browser_context is None:
            self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
            self._browser_context = playwright.chromium.launch_persistent_context(
                str(self.config.user_data_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
                viewport={"width": 1280, "height": 900},
            )
            self._browser_context.set_default_timeout(0)
            self._browser_context.set_default_navigation_timeout(0)
        return self._browser_context

    def _ensure_page(self, browser) -> Page:
        if self._page is None:
            self._page = browser.new_page()
            self._page.set_default_timeout(0)
            self._page.set_default_navigation_timeout(0)
        return self._page

    def _refresh_trade_tab(self, page: Page) -> Page:
        if not self._browser_context:
            return page
        old_page = page
        new_page: Optional[Page] = None
        try:
            old_page.bring_to_front()
            old_page.keyboard.press("Meta+W")
            old_page.wait_for_event("close", timeout=2000)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to close tab via shortcut; closing directly")
            try:
                old_page.close()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Failed to close previous tab")
        try:
            active_page = next(
                (candidate for candidate in self._browser_context.pages if not candidate.is_closed()),
                None,
            )
            if active_page is None:
                active_page = self._browser_context.new_page()
            active_page.bring_to_front()
            active_page.keyboard.press("Meta+T")
            new_page = self._browser_context.wait_for_event("page", timeout=5000)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to open new tab via shortcut; opening directly")
        if new_page is None:
            new_page = self._browser_context.new_page()
        new_page.set_default_timeout(0)
        new_page.set_default_navigation_timeout(0)
        self._page = new_page
        logging.info("Opened new tab for next trade cycle")
        return new_page

    def _stop_requested(self) -> bool:
        return bool(self.stop_controller and self.stop_controller.stop_requested())

    def _start_tracing(self, browser) -> None:
        try:
            browser.tracing.start(screenshots=True, snapshots=True, sources=True)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to start tracing")

    def _read_next_event(self, path: Path) -> Optional[tuple[dict[str, Any], str]]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logging.warning("Invalid JSON in %s; skipping line", path)
                        continue
                    event_key = self._event_key(event)
                    if event_key == self.state.last_event_key:
                        return None
                    return event, event_key
        except OSError as exc:
            logging.warning("Unable to read %s: %s", path, exc)
        return None

    def _mark_event_processed(self, event_key: str) -> None:
        if event_key == self.state.last_event_key:
            return
        self.state.last_event_key = event_key
        self.state.save(self.config.state_path)

    def _event_key(self, event: dict[str, Any]) -> str:
        tx_hash = event.get("tx_hash")
        if tx_hash:
            return f"tx:{tx_hash}"
        return json.dumps(event, sort_keys=True, separators=(",", ":"))

    def _sleep_until_next_minute(self) -> None:
        interval = max(1, self.config.trade_poll_interval_seconds)
        if interval != 30:
            remaining = float(interval)
            while not self._stop_requested() and remaining > 0:
                sleep_for = min(remaining, 5)
                time.sleep(sleep_for)
                remaining -= sleep_for
            return
        while not self._stop_requested():
            now = datetime.now(self.config.timezone)
            target = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 5))
