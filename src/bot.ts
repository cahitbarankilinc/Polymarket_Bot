import path from 'path';
import { chromium, type Page, type Locator } from 'playwright';
import type { Config } from './config.js';
import { getLocator } from './selectors.js';
import { logMessage, parsePrice, ensureDir, formatTimestamp, sanitizeFileName } from './utils.js';
import { BotState, isPaused, setPause } from './state.js';

const DEFAULT_TIMEOUT = 15000;

async function readPrice(page: Page, key: 'priceToBeatValue' | 'currentPriceValue'): Promise<number> {
  const locator = getLocator(page, key);
  await locator.waitFor({ state: 'visible', timeout: DEFAULT_TIMEOUT });
  const text = (await locator.textContent())?.trim();
  if (!text) {
    throw new Error(`Unable to read ${key}`);
  }
  return parsePrice(text);
}

async function fillInput(locator: Locator, value: number | string): Promise<void> {
  await locator.waitFor({ state: 'visible', timeout: DEFAULT_TIMEOUT });
  await locator.click({ timeout: DEFAULT_TIMEOUT });
  await locator.press('Control+A');
  await locator.press('Backspace');
  await locator.type(String(value), { delay: 10 });
}

export async function runOnce(config: Config, state: BotState): Promise<BotState> {
  const now = Date.now();
  if (isPaused(state, now)) {
    logMessage(config.runsDir, `Skipping run because bot is paused until ${new Date(state.pauseUntil!).toISOString()}`, config.timezone);
    return state;
  }

  ensureDir(config.storageDir);
  ensureDir(config.runsDir);
  const profilePath = path.join(config.storageDir, 'profile');
  const startTime = formatTimestamp(new Date(), config.timezone);
  const traceName = sanitizeFileName(`trace-${startTime}`) + '.zip';
  const screenshotName = sanitizeFileName(`screenshot-${startTime}`) + '.png';
  const tracePath = path.join(config.runsDir, traceName);
  const screenshotPath = path.join(config.runsDir, screenshotName);

  logMessage(config.runsDir, `Starting run at ${startTime}`, config.timezone);

  const context = await chromium.launchPersistentContext(profilePath, {
    headless: config.headless,
    timezoneId: config.timezone
  });
  const page = context.pages()[0] ?? (await context.newPage());

  let tracingStopped = false;
  const stopTracing = async (pathArg?: string) => {
    if (tracingStopped) return;
    tracingStopped = true;
    try {
      await context.tracing.stop(pathArg ? { path: pathArg } : undefined);
    } catch (error) {
      console.error('Failed to stop tracing', error);
    }
  };

  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });

  try {
    await page.goto(config.marketUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const titleLocator = getLocator(page, 'marketTitle');
    await titleLocator.waitFor({ state: 'visible', timeout: DEFAULT_TIMEOUT });
    const titleText = (await titleLocator.textContent())?.trim();
    if (!titleText || !/bitcoin up or down/i.test(titleText)) {
      throw new Error('Market title did not match expected "Bitcoin Up or Down"');
    }

    const priceToBeat = await readPrice(page, 'priceToBeatValue');
    const currentPrice = await readPrice(page, 'currentPriceValue');
    const diff = Math.abs(currentPrice - priceToBeat);
    logMessage(
      config.runsDir,
      `Read prices - PRICE TO BEAT: ${priceToBeat}, CURRENT PRICE: ${currentPrice}, diff: ${diff}`,
      config.timezone
    );

    if (diff > config.diffThresholdUsd) {
      const pauseUntil = Date.now() + config.pauseMinutes * 60 * 1000;
      await page.screenshot({ path: screenshotPath, fullPage: true });
      await stopTracing(tracePath);
      logMessage(
        config.runsDir,
        `Diff ${diff} exceeds threshold ${config.diffThresholdUsd}. Pausing until ${new Date(pauseUntil).toISOString()}. Screenshot: ${screenshotPath}, trace: ${tracePath}`,
        config.timezone
      );
      await context.close();
      return setPause(state, pauseUntil);
    }

    await getLocator(page, 'buyTab').click({ timeout: DEFAULT_TIMEOUT });
    const sideLocator = config.side === 'UP' ? getLocator(page, 'upButton') : getLocator(page, 'downButton');
    await sideLocator.waitFor({ state: 'visible', timeout: DEFAULT_TIMEOUT });
    await sideLocator.click({ timeout: DEFAULT_TIMEOUT });

    await fillInput(getLocator(page, 'limitPriceInput'), config.limitPrice);
    await fillInput(getLocator(page, 'sharesInput'), config.shares);

    const placeButton = getLocator(page, 'placeOrderButton');
    await placeButton.waitFor({ state: 'visible', timeout: DEFAULT_TIMEOUT });
    const enabled = await placeButton.isEnabled();
    if (!enabled) {
      throw new Error('Place order button is disabled; aborting run.');
    }

    await placeButton.click({ timeout: DEFAULT_TIMEOUT });
    try {
      await getLocator(page, 'confirmationToast').waitFor({ state: 'visible', timeout: 8000 });
      logMessage(config.runsDir, 'Detected confirmation toast after placing order.', config.timezone);
    } catch {
      logMessage(config.runsDir, 'No confirmation toast detected within timeout; verify manually.', config.timezone);
    }

    logMessage(config.runsDir, 'Order flow completed without fatal errors.', config.timezone);
    await stopTracing();
    await context.close();
    return state;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    await stopTracing(tracePath);
    logMessage(
      config.runsDir,
      `Run failed: ${message}. Screenshot: ${screenshotPath}, trace: ${tracePath}`,
      config.timezone
    );
    await context.close();
    return state;
  }
}
