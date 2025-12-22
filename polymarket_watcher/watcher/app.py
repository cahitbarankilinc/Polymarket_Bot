from __future__ import annotations

import asyncio
import logging
import re
import signal
from datetime import datetime
from pathlib import Path
from typing import Tuple

from playwright.async_api import Page, async_playwright
from zoneinfo import ZoneInfo

from . import selectors
from .config import Config, load_config
from .state import BotState
from .utils import (
    append_result_line,
    current_bucket_times_berlin,
    event_timestamp_from_bucket_start,
    parse_price,
)


def get_berlin_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Invalid TIMEZONE_BERLIN %s; falling back to Europe/Berlin", timezone_name)
        return ZoneInfo("Europe/Berlin")


async def capture_screenshot(page: Page, directory: Path, prefix: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
        logging.info("Saved screenshot to %s", path)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.warning("Unable to capture screenshot: %s", exc)


async def launch_context(playwright, config: Config):
    config.user_data_dir.mkdir(parents=True, exist_ok=True)
    launch_kwargs = {
        "user_data_dir": config.user_data_dir,
        "headless": config.headless,
    }
    try:
        return await playwright.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
    except Exception as exc:  # pylint: disable-broad-exception-caught
        logging.warning("Chrome channel launch failed (%s); retrying without channel", exc)
        return await playwright.chromium.launch_persistent_context(**launch_kwargs)


async def wait_for_trade_widget(page: Page, config: Config) -> None:
    widget = selectors.trade_widget(page)
    screenshot_taken = False

    for attempt in range(2):
        waited = 0
        while waited < 20000:
            try:
                if await widget.count() > 0:
                    logging.info("Trade widget detected after %.1fs", waited / 1000)
                    return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.debug("Widget count attempt failed: %s", exc)
            await page.wait_for_timeout(200)
            waited += 200

        if not screenshot_taken:
            logging.warning("Trade widget not found within timeout; capturing screenshot and retrying")
            await capture_screenshot(page, config.screenshot_dir, "missing-trade-widget")
            screenshot_taken = True

    raise RuntimeError("Trade widget not visible after retries")


async def fetch_button_texts(page: Page) -> dict[str, str | None]:
    return await page.evaluate(
        """
        () => {
          const w = document.querySelector('#trade-widget') || document;
          const buttons = Array.from(w.querySelectorAll('button'));
          const upBtn = buttons.find(b => /\\bUp\\b/i.test(b.textContent || ''));
          const downBtn = buttons.find(b => /\\bDown\\b/i.test(b.textContent || ''));
          return {
            upText: upBtn ? (upBtn.textContent || '').trim() : null,
            downText: downBtn ? (downBtn.textContent || '').trim() : null,
          };
        }
        """
    )


async def ensure_buy_tab_selected(page: Page) -> bool:
    buy_tab = page.get_by_role("tab", name=re.compile(r"\\bBuy\\b", re.I)).first
    if await buy_tab.count() == 0:
        logging.debug("Buy tab not found on page")
        return False

    try:
        is_selected = await buy_tab.get_attribute("aria-selected")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.debug("Unable to read buy tab state: %s", exc)
        is_selected = None

    if isinstance(is_selected, str) and is_selected.lower() == "true":
        return True

    try:
        await buy_tab.click()
        await page.wait_for_timeout(200)
        logging.info("Switched to Buy tab")
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.warning("Failed to select Buy tab: %s", exc)
        return False


async def read_prices(page: Page, config: Config) -> Tuple[int, int, str, str]:
    await wait_for_trade_widget(page, config)

    prices = await fetch_button_texts(page)
    if prices["upText"] is None and prices["downText"] is None:
        if await ensure_buy_tab_selected(page):
            prices = await fetch_button_texts(page)

    up_text = prices.get("upText")
    down_text = prices.get("downText")
    if up_text is None or down_text is None:
        raise RuntimeError(f"Unable to read button text (Up: {up_text!r}, Down: {down_text!r})")

    up_price = parse_price(up_text)
    down_price = parse_price(down_text)
    if up_price is None or down_price is None:
        await capture_screenshot(page, config.screenshot_dir, "unparsed-prices")
        raise RuntimeError(f"Unable to parse prices (Up: {up_text!r}, Down: {down_text!r})")

    logging.info("Current prices | Up: %s¢ | Down: %s¢", up_price, down_price)
    return up_price, down_price, up_text, down_text


async def evaluate_once(
    page: Page,
    config: Config,
    state: BotState,
    berlin_zone: ZoneInfo,
    current_page_ts: int | None,
) -> tuple[float, int | None]:
    now_berlin = datetime.now(berlin_zone)
    bucket_start_berlin, close_dt = current_bucket_times_berlin(now_berlin)
    event_ts = event_timestamp_from_bucket_start(bucket_start_berlin)
    event_slug = f"btc-updown-15m-{event_ts}"
    event_url = f"{config.base_event_url}{event_ts}"

    logging.info(
        "Timing | now_berlin=%s | bucket_start=%s | close_berlin=%s | ts=%s | event_url=%s",
        now_berlin.isoformat(),
        bucket_start_berlin.isoformat(),
        close_dt.isoformat(),
        event_ts,
        event_url,
    )

    if state.has_logged(event_ts):
        sleep_seconds = max(1, int((close_dt - now_berlin).total_seconds()))
        logging.info("Timestamp %s already recorded; sleeping %ss", event_slug, sleep_seconds)
        return float(sleep_seconds), current_page_ts

    if current_page_ts != event_ts:
        logging.info("Navigating to event: %s", event_url)
        await page.goto(event_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(500)
        current_page_ts = event_ts

    up_price, down_price, up_text, down_text = await read_prices(page, config)
    result = "Won" if up_price == down_price else "Lost"

    line_timestamp = now_berlin.isoformat()
    append_result_line(config.results_file, f"{line_timestamp} | {event_slug} | {result}\n")
    state.mark_logged(event_ts, config.state_file)
    logging.info(
        "Recorded result for %s: %s (Up button: %s, Down button: %s)",
        event_slug,
        result,
        up_text,
        down_text,
    )
    return float(config.poll_seconds), current_page_ts


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    config = load_config()
    state = BotState.load(config.state_file)
    berlin_zone = get_berlin_zone(config.timezone_berlin)
    logging.info("Loaded state with %s logged timestamps", len(state.logged_timestamps))

    stop_event = asyncio.Event()

    def _handle_stop() -> None:
        logging.info("Stop requested; finishing current iteration")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_stop)
        except NotImplementedError:
            # Fallback for platforms without signal support
            signal.signal(sig, lambda *_: _handle_stop())

    playwright = await async_playwright().start()
    browser = await launch_context(playwright, config)
    page = browser.pages[0] if browser.pages else await browser.new_page()
    current_page_ts: int | None = None

    try:
        while not stop_event.is_set():
            try:
                sleep_for, current_page_ts = await evaluate_once(
                    page, config, state, berlin_zone, current_page_ts
                )
                await asyncio.sleep(sleep_for)
            except Exception as exc:  # pylint: disable-broad-exception-caught
                logging.exception("Iteration failed: %s", exc)
                await capture_screenshot(page, config.screenshot_dir, "error")
                await asyncio.sleep(5)
    finally:
        if config.auto_close_browser:
            logging.info("Closing browser and playwright (AUTO_CLOSE_BROWSER=true)")
            await browser.close()
            await playwright.stop()
        else:
            logging.info("AUTO_CLOSE_BROWSER=false: leaving browser open for manual inspection")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
