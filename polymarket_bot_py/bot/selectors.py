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
        logging.info("Ensuring limit mode")
        if self._limit_already_selected():
            logging.info("Limit mode already active")
            return

        dropdown = self._find_order_type_toggle()
        if dropdown is None:
            logging.warning("Order type toggle not found; continuing without switching to Limit")
            return

        if not self._click_with_poll(dropdown, "order type dropdown"):
            logging.warning("Unable to open order type dropdown; continuing without switching to Limit")
            return

        option = self._find_limit_option()
        if option is None:
            logging.warning("Limit option not found; continuing")
            return

        if not self._click_with_poll(option, "limit option"):
            logging.warning("Failed to click limit option; continuing")

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

    def _click_with_poll(self, locator: Locator, description: str, attempts: int = 30, interval_ms: int = 1000) -> bool:
        for attempt in range(1, attempts + 1):
            if self._is_visible(locator):
                try:
                    locator.click()
                    return True
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logging.debug("Click failed for %s: %s", description, exc)
            logging.info("Waiting for %s (attempt %s/%s)", description, attempt, attempts)
            self.page.wait_for_timeout(interval_ms)
        logging.warning("%s not clickable after %s attempts", description, attempts)
        return False

    def _is_visible(self, locator: Locator) -> bool:
        try:
            return locator.is_visible()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.debug("Visibility check failed for locator: %s", exc)
            return False

    def _limit_already_selected(self) -> bool:
        candidates = [
            self.trade_widget.get_by_role("button", name=re.compile("limit", re.I)).first,
            self.trade_widget.get_by_text("Limit", exact=False).first,
            self.page.get_by_role("button", name=re.compile("limit", re.I)).first,
            self.page.get_by_text("Limit", exact=False).first,
        ]
        for locator in candidates:
            if self._is_visible(locator):
                return True
        return False

    def _find_order_type_toggle(self) -> Optional[Locator]:
        candidates = [
            self.trade_widget.get_by_text("Market", exact=False).first,
            self.trade_widget.get_by_role("button", name=re.compile("market", re.I)).first,
            self.page.get_by_text("Market", exact=False).first,
            self.page.get_by_role("button", name=re.compile("market", re.I)).first,
        ]
        for locator in candidates:
            if self._is_visible(locator):
                return locator
        return None

    def _find_limit_option(self) -> Optional[Locator]:
        candidates = [
            self.trade_widget.get_by_role("menuitemradio", name=re.compile("limit", re.I)).first,
            self.page.get_by_role("menuitemradio", name=re.compile("limit", re.I)).first,
        ]
        for locator in candidates:
            if self._is_visible(locator):
                return locator
        return None

    def ensure_widget_ready(self) -> None:
        self._wait_visible(self.trade_widget, "trade widget root")
        cent_inputs = self.trade_widget.get_by_role("textbox", name="¢")
        if cent_inputs.count() > 0:
            self._wait_visible(cent_inputs.first, "cent price input")

