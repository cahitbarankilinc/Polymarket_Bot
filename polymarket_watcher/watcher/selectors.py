from __future__ import annotations

from playwright.async_api import Locator, Page


def trade_widget(page: Page) -> Locator:
    return page.locator("#trade-widget")


def event_heading(page: Page) -> Locator:
    return page.get_by_role("heading", level=1).first
