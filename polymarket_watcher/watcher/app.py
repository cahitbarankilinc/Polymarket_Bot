from __future__ import annotations

import asyncio
import logging
import re
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlsplit

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from . import selectors
from .config import Config, load_config
from .state import BotState
from .utils import append_result_line, most_common_text, parse_price, safe_event_key, timestamp_now


async def capture_screenshot(page: Page, directory: Path, prefix: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"{prefix}-{timestamp}.png"
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
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.warning("Chrome channel launch failed (%s); retrying without channel", exc)
        return await playwright.chromium.launch_persistent_context(**launch_kwargs)


async def open_event_listing(page: Page, config: Config) -> None:
    logging.info("Navigating to listing: %s", config.home_15m_url)
    await page.goto(config.home_15m_url, wait_until="domcontentloaded")
    card = selectors.market_card(page, config.card_text)
    try:
        await card.wait_for(state="visible", timeout=20000)
    except PlaywrightTimeoutError:
        raise RuntimeError("Market card not found on listing page")
    await card.click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(500)


async def extract_event_key(page: Page) -> Optional[str]:
    parsed = urlsplit(page.url)
    match = re.search(r"/event/([^/?#]+)", parsed.path)
    if match:
        return safe_event_key(match.group(1))

    try:
        heading = selectors.event_heading(page)
        title = await heading.text_content()
    except Exception:  # pylint: disable=broad-exception-caught
        title = ""
    try:
        time_text = await page.get_by_text("ET", exact=False).first.text_content()
    except Exception:  # pylint: disable=broad-exception-caught
        time_text = ""

    combined = " ".join(filter(None, [title, time_text])).strip()
    if combined:
        return safe_event_key(combined)
    return None


async def sample_button_text(page: Page, locator, retries: int, delay_ms: int) -> str:
    samples = []
    for attempt in range(1, retries + 1):
        try:
            samples.append(await locator.inner_text())
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.debug("Attempt %s/%s: unable to read text (%s)", attempt, retries, exc)
        await page.wait_for_timeout(delay_ms)
    value = most_common_text(samples)
    if not value:
        raise RuntimeError("Could not capture button text")
    return value


async def read_prices(page: Page, config: Config) -> Tuple[int, int, str, str]:
    widget = selectors.trade_widget(page)
    try:
        await widget.wait_for(state="visible", timeout=20000)
    except PlaywrightTimeoutError:
        raise RuntimeError("Trade widget not visible")

    up_btn = selectors.up_button(widget)
    down_btn = selectors.down_button(widget)
    await asyncio.gather(
        up_btn.wait_for(state="visible", timeout=15000),
        down_btn.wait_for(state="visible", timeout=15000),
    )

    up_text = await sample_button_text(page, up_btn, config.sample_retries, config.sample_delay_ms)
    down_text = await sample_button_text(page, down_btn, config.sample_retries, config.sample_delay_ms)

    up_price = parse_price(up_text)
    down_price = parse_price(down_text)
    if up_price is None or down_price is None:
        raise RuntimeError(f"Unable to parse prices (Up: {up_text!r}, Down: {down_text!r})")

    logging.info("Current prices | Up: %s¢ | Down: %s¢", up_price, down_price)
    return up_price, down_price, up_text, down_text


async def evaluate_once(page: Page, config: Config, state: BotState) -> None:
    await open_event_listing(page, config)
    event_key = await extract_event_key(page)
    if not event_key:
        raise RuntimeError("Could not determine event identifier")

    if state.has_seen(event_key):
        logging.info("Event %s already recorded; sleeping %ss", event_key, config.poll_seconds)
        return

    up_price, down_price, up_text, down_text = await read_prices(page, config)
    result = "Won" if up_price == down_price else "Lost"

    timestamp = timestamp_now(config.timezone)
    append_result_line(config.results_file, f"{timestamp} | {event_key} | {result}\n")
    state.mark_seen(event_key, config.state_file)
    logging.info(
        "Recorded result for %s: %s (Up button: %s, Down button: %s)",
        event_key,
        result,
        up_text,
        down_text,
    )


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    config = load_config()
    state = BotState.load(config.state_file)
    logging.info("Loaded state with %s seen events", len(state.seen_events))

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

    try:
        while not stop_event.is_set():
            try:
                await evaluate_once(page, config, state)
                await asyncio.sleep(config.poll_seconds)
            except Exception as exc:  # pylint: disable=broad-exception-caught
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
