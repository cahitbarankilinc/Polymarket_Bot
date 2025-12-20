import type { Locator, Page } from 'playwright';

type LocatorFactory = (page: Page) => Locator;

export const selectors: Record<string, LocatorFactory> = {
  marketTitle: (page) => page.getByRole('heading', { name: /bitcoin up or down/i }),
  priceToBeatLabel: (page) => page.getByText(/price to beat/i),
  priceToBeatValue: (page) =>
    page.locator('text=/price to beat/i').locator('xpath=following::*[1][self::span or self::div]'),
  currentPriceLabel: (page) => page.getByText(/current price/i),
  currentPriceValue: (page) =>
    page.locator('text=/current price/i').locator('xpath=following::*[1][self::span or self::div]'),
  buyTab: (page) => page.getByRole('tab', { name: /buy/i }),
  sellTab: (page) => page.getByRole('tab', { name: /sell/i }),
  upButton: (page) => page.getByRole('button', { name: /up/i }),
  downButton: (page) => page.getByRole('button', { name: /down/i }),
  limitPriceInput: (page) => page.getByLabel(/limit price/i).or(page.getByPlaceholder(/limit/i)),
  sharesInput: (page) => page.getByLabel(/shares/i).or(page.getByPlaceholder(/shares/i)),
  placeOrderButton: (page) =>
    page.getByRole('button', { name: /place order|buy|place trade|place/i }).first(),
  confirmationToast: (page) => page.getByText(/order placed|success|filled|confirmed/i)
};

export type SelectorKey = keyof typeof selectors;

export function getLocator(page: Page, key: SelectorKey): Locator {
  const factory = selectors[key];
  if (!factory) {
    throw new Error(`Unknown selector key: ${key}`);
  }
  return factory(page);
}
