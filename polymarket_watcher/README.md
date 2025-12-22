# Polymarket Watcher Bot

Headful Playwright watcher that generates the current Bitcoin 15-minute event URL from the active Berlin bucket (0/15/30/45), reads the Up/Down button prices, and logs a Won/Lost verdict per event. The bot never clicks trade – it only records one line per event in `results.txt`.

## Features
- Persistent Chromium profile via `launch_persistent_context` so login cookies stay intact.
- Headful by default (`HEADLESS=false`) for easy monitoring.
- Stops on Ctrl+C without closing the browser unless `AUTO_CLOSE_BROWSER=true`.
- Error tolerance: missing selectors or parse errors are logged, a screenshot is saved, and the bot retries after 5 seconds.
- Bot screenshot almaz; sadece hata olursa alır.
- Debounced logging: when a timestamp has already been recorded, the bot sleeps until the next 15-minute bucket.
- Event URL is produced as `https://polymarket.com/event/btc-updown-15m-<UTC_BUCKET_START_TIMESTAMP>`, where the timestamp is the UTC Unix seconds for the bucket start. Buckets advance by 900 seconds (15 minutes).

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

## How the event URL is built
- Berlin time determines the current bucket (minutes 0, 15, 30, 45). For example, 12:07 → 12:00:00 bucket start; 12:15:01 → 12:15:00 bucket start.
- The bucket start time is converted to UTC, then to a Unix timestamp (seconds). That timestamp is appended to `BASE_EVENT_URL` (default `https://polymarket.com/event/btc-updown-15m-`).
- Buckets are 900 seconds apart, so each new market increments the trailing timestamp by 900.

## Output
- Results are appended to `results.txt` in the format (timestamp in Berlin time, event slug from the UTC bucket-start timestamp):
  ```
  2025-12-22T01:06:42+01:00 | btc-updown-15m-1734837300 | Won
  2025-12-22T01:21:42+01:00 | btc-updown-15m-1734838200 | Lost
  ```
- State of logged bucket timestamps is stored in `state.json` to avoid duplicate lines.
- Error screenshots are saved under `screenshots/`.
