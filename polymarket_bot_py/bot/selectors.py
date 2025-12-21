from __future__ import annotations

import re
from playwright.sync_api import Locator, Page, expect


class TradePage:
    def __init__(self, page: Page):
        self.page = page

    def open_market_card(self, card_text: str) -> None:
        card = self.page.get_by_text(card_text, exact=False).first
        expect(card).to_be_visible(timeout=15000)
        card.click()

    def ensure_limit_mode(self) -> None:
        dropdown = self.page.get_by_role("button", name=re.compile("order type|limit", re.I)).first
        expect(dropdown).to_be_visible(timeout=10000)
        dropdown.click()
        option = self.page.get_by_role("menuitemradio", name=re.compile("limit", re.I))
        expect(option).to_be_visible(timeout=5000)
        option.click()

    def select_side(self, side: str) -> None:
        side_locator = self.page.get_by_role("radio", name=re.compile(side, re.I))
        expect(side_locator).to_be_visible(timeout=5000)
        side_locator.click()

    def fill_limit_price(self, value_cents: float) -> None:
        locator = self._input_by_label("Limit Price")
        locator.fill(str(value_cents))

    def fill_shares(self, shares: float) -> None:
        locator = self._input_by_label("Shares")
        locator.fill(str(shares))

    def trade_button(self) -> Locator:
        button = self.page.get_by_role("button", name=re.compile("trade", re.I))
        expect(button).to_be_visible(timeout=5000)
        return button

    def prices(self) -> tuple[float, float]:
        beat_label = self.page.get_by_text("Price to beat", exact=False).first
        current_label = self.page.get_by_text("Current price", exact=False).first
        expect(beat_label).to_be_visible(timeout=5000)
        expect(current_label).to_be_visible(timeout=5000)
        beat_value = beat_label.locator("xpath=following::*[contains(text(), '$')][1]")
        current_value = current_label.locator("xpath=following::*[contains(text(), '$')][1]")
        expect(beat_value).to_be_visible(timeout=5000)
        expect(current_value).to_be_visible(timeout=5000)
        return beat_value.inner_text(), current_value.inner_text()

    def _input_by_label(self, label_text: str) -> Locator:
        labelled = self.page.get_by_label(label_text, exact=False)
        if labelled.count() > 0:
            expect(labelled.first).to_be_visible(timeout=5000)
            return labelled.first
        # fallback: label followed by input
        locator = self.page.locator(
            f"xpath=//label[contains(normalize-space(), '{label_text}')]/following::*[self::input or self::textarea][1]"
        )
        expect(locator).to_be_visible(timeout=5000)
        return locator

