from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright
from zoneinfo import ZoneInfo

from . import selectors
from .config import Config, load_config
from .state import BotState
from .utils import (
    append_result_line,
    current_bucket_close_time_berlin,
    current_bucket_times_berlin,
    event_timestamp_from_bucket_start,
    most_common_text,
    parse_price,
)


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


async def evaluate_once(page: Page, config: Config, state: BotState) -> float:
    try:
        berlin_zone = ZoneInfo(config.timezone_berlin)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Invalid TIMEZONE_BERLIN %s; falling back to Europe/Berlin", config.timezone_berlin)
        berlin_zone = ZoneInfo("Europe/Berlin")

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

    if state.has_seen(event_ts):
        next_bucket = current_bucket_close_time_berlin(close_dt + timedelta(seconds=1))
        sleep_seconds = max(1, int((next_bucket - now_berlin).total_seconds()))
        logging.info("Timestamp %s already recorded; sleeping %ss", event_slug, sleep_seconds)
        return sleep_seconds

    logging.info("Navigating to event: %s", event_url)
    await page.goto(event_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(500)

    up_price, down_price, up_text, down_text = await read_prices(page, config)
    result = "Won" if up_price == down_price else "Lost"

    line_timestamp = now_berlin.isoformat()
    append_result_line(config.results_file, f"{line_timestamp} | {event_slug} | {result}\n")
    state.mark_seen(event_ts, config.state_file)
    logging.info(
        "Recorded result for %s: %s (Up button: %s, Down button: %s)",
        event_slug,
        result,
        up_text,
        down_text,
    )
    return float(config.poll_seconds)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    config = load_config()
    state = BotState.load(config.state_file)
    logging.info("Loaded state with %s seen timestamps", len(state.seen_timestamps))

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
                sleep_for = await evaluate_once(page, config, state)
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
