from __future__ import annotations

import logging
import re
from typing import Optional
from playwright.sync_api import Locator, Page


class TradePage:
    def __init__(self, page: Page):
        self.page = page
        self.trade_widget = self.page.locator("#trade-widget").first

    def open_market_card(self, card_text: str) -> None:
        card = self.page.get_by_text(card_text, exact=False).first
        self._wait_visible(card, "market card")
        card.click()

    def ensure_limit_mode(self) -> None:
        dropdown = self.trade_widget.get_by_role("button", name=re.compile("order type|limit", re.I)).first
        self._wait_visible(dropdown, "order type dropdown")
        dropdown.click()
        option = self.page.get_by_role("menuitemradio", name=re.compile("limit", re.I)).first
        self._wait_visible(option, "limit option")
        option.click()

    def select_side(self, side: str) -> None:
        side_locator = self.trade_widget.get_by_role("radio", name=re.compile(rf"\b{side}\b", re.I)).first
        self._wait_visible(side_locator, f"{side} side")
        side_locator.click()

    def fill_limit_price(self, value_cents: float) -> None:
        locator = self._limit_price_input()
        locator.fill(str(value_cents))

    def fill_shares(self, shares: float) -> None:
        locator = self._shares_input()
        locator.fill(str(shares))

    def trade_button(self) -> Locator:
        button = self.trade_widget.get_by_role("button", name=re.compile("trade", re.I)).first
        self._wait_visible(button, "trade button")
        return button

    def prices(self) -> tuple[float, float]:
        beat_label = self.page.get_by_text("Price to beat", exact=False).first
        current_label = self.page.get_by_text("Current price", exact=False).first
        self._wait_visible(beat_label, "Price to beat label")
        self._wait_visible(current_label, "Current price label")
        beat_value = beat_label.locator("xpath=following::*[contains(text(), '$')][1]")
        current_value = current_label.locator("xpath=following::*[contains(text(), '$')][1]")
        self._wait_visible(beat_value, "Price to beat value")
        self._wait_visible(current_value, "Current price value")
        return beat_value.inner_text(), current_value.inner_text()

    def _input_by_label(self, label_text: str) -> Optional[Locator]:
        labelled = self.trade_widget.get_by_label(label_text, exact=False)
        if labelled.count() > 0:
            locator = labelled.first
            self._wait_visible(locator, f"{label_text} input")
            return locator
        # fallback: label followed by input within widget
        locator = self.trade_widget.locator(
            f"xpath=.//label[contains(normalize-space(), '{label_text}')]/following::*[self::input or self::textarea][1]"
        )
        if locator.count() > 0:
            self._wait_visible(locator.first, f"{label_text} input")
            return locator.first
        return None

    def _shares_input(self) -> Locator:
        locator = self.trade_widget.get_by_role("textbox", name="0", exact=True).first
        self._wait_visible(locator, "shares input")
        return locator

    def _limit_price_input(self) -> Locator:
        labelled = self._input_by_label("Limit Price")
        if labelled:
            return labelled
        price_boxes = self.trade_widget.get_by_role("textbox", name="¢")
        if price_boxes.count() > 0:
            locator = price_boxes.first
            self._wait_visible(locator, "limit price input")
            return locator
        raise RuntimeError("Limit price input not found")

    def _wait_visible(self, locator: Locator, description: str, attempts: int = 30, interval_ms: int = 1000) -> None:
        for attempt in range(1, attempts + 1):
            try:
                if locator.is_visible():
                    return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.debug("Visibility check failed for %s: %s", description, exc)
            logging.info("Waiting for %s (attempt %s/%s)", description, attempt, attempts)
            self.page.wait_for_timeout(interval_ms)
        raise RuntimeError(f"{description} not visible after waiting")

    def ensure_widget_ready(self) -> None:
        self._wait_visible(self.trade_widget, "trade widget root")
        cent_inputs = self.trade_widget.get_by_role("textbox", name="¢")
        if cent_inputs.count() > 0:
            self._wait_visible(cent_inputs.first, "cent price input")

