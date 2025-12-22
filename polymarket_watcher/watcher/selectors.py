from __future__ import annotations

import re
from playwright.async_api import Locator, Page


def market_card(page: Page, card_text: str) -> Locator:
    return page.get_by_text(card_text, exact=False).first


def trade_widget(page: Page) -> Locator:
    return page.locator("#trade-widget").first


def up_button(widget: Locator) -> Locator:
    return widget.get_by_role("button").filter(has_text=re.compile(r"\bUp\b", re.I)).first


def down_button(widget: Locator) -> Locator:
    return widget.get_by_role("button").filter(has_text=re.compile(r"\bDown\b", re.I)).first


def event_heading(page: Page) -> Locator:
    return page.get_by_role("heading", level=1).first
