# Polymarket Playwright Bot

Production-style Playwright automation for the Polymarket 15-minute Bitcoin market. The bot keeps a persistent browser session, fills the Limit order form, and (when `DRY_RUN=false`) clicks the Trade button. It runs on a 15-minute cadence (00/15/30/45) with fail-closed safeguards.

## Features
- Persistent Chromium profile via `launch_persistent_context` (login cookies retained).
- Fail-closed checks: if selectors or market widgets are missing, the bot exits without clicking Trade.
- DRY_RUN mode (default) fills the form without submitting.
- ESC listener: pressing ESC sets a stop flag ("STOP requested by ESC") and halts the loop without closing the browser.
- Pause rule: if `|CURRENT PRICE - PRICE TO BEAT|` exceeds `DIFF_THRESHOLD_USD`, skip trading for `PAUSE_MINUTES`.
- Run artifacts per execution: `runs/YYYYMMDD/HHMMSS/` containing logs, screenshots, and Playwright trace.
- Scheduler loop or one-off execution (`--once`).

## Quickstart
1. Create a virtualenv and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install
   ```
2. Copy the example environment file and adjust values:
   ```bash
   cp .env.example .env
   ```
3. First run should be headful so you can log into Polymarket inside the persistent profile:
   ```bash
   HEADLESS=false python -m bot.main --once
   ```
4. Start the scheduler loop (runs every 15 minutes):
   ```bash
   python -m bot.main
   ```

## Environment variables
Defined in `.env.example`:
- `HOME_15M_URL` – listing page for the rotating event link.
- `CARD_TEXT` – text of the event card to enter.
- `SIDE` – `UP` or `DOWN` radio selection.
- `LIMIT_PRICE_CENTS` – limit price to input (cents).
- `SHARES` – number of shares to buy.
- `DIFF_THRESHOLD_USD` – pause if price gap exceeds this amount.
- `PAUSE_MINUTES` – pause duration when the threshold is hit.
- `TIMEZONE` – tz database name for scheduling buckets.
- `HEADLESS` – `true/false` browser headless mode.
- `DRY_RUN` – `true/false`; when true, the Trade button is not clicked.
- `AUTO_CLOSE_BROWSER` – default `false`; when false, the browser/context is left running (ESC/Ctrl+C do not close it).
- `USER_DATA_DIR` – path for Chromium profile (persist login).
- `SLOW_MO_MS` – Playwright slow motion delay per action.

## Running
- **Scheduler loop:** `python -m bot.main`
- **One-off test:** `python -m bot.main --once`

Run artifacts are stored under `runs/` and state is tracked in `state.json` (last bucket, pause timestamp).

