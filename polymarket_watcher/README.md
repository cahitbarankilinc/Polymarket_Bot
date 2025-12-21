# Polymarket Watcher Bot

Headful Playwright watcher that visits the 15-minute Bitcoin market, reads the Up/Down button prices, and logs a Won/Lost verdict per event. The bot never clicks trade – it only records one line per event in `results.txt`.

## Features
- Persistent Chromium profile via `launch_persistent_context` so login cookies stay intact.
- Headful by default (`HEADLESS=false`) for easy monitoring.
- Stops on Ctrl+C without closing the browser unless `AUTO_CLOSE_BROWSER=true`.
- Error tolerance: missing selectors or parse errors are logged, a screenshot is saved, and the bot retries after 5 seconds.
- Debounced logging: when an event has already been recorded, the bot sleeps for `POLL_SECONDS` before re-checking.

## Quickstart
1. Install dependencies:
   ```bash
   cd polymarket_watcher
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```
2. Configure environment variables:
   ```bash
   cp .env.example .env
   ```
   Adjust values as needed (defaults match the provided example).
3. Start the watcher (headful by default):
   ```bash
   python -m watcher.app
   ```
4. Stop with `Ctrl+C` when desired. If `AUTO_CLOSE_BROWSER=false`, the Chrome window remains open for manual inspection.

## Output
- Results are appended to `results.txt` in the format:
  ```
  2025-12-22T01:06:42+03:00 | <event_key> | Won
  2025-12-22T01:21:42+03:00 | <event_key> | Lost
  ```
- State of seen events is stored in `state.json` to avoid duplicate lines.
- Error screenshots are saved under `screenshots/`.
