# Polymarket Bot

See `polymarket_bot_py/README.md` for usage instructions and project layout for the Playwright-based automation bot.

## Real-time activity tracker (new)

A standalone Python script, `track_polymarket_activity.py`, polls Polymarket's public data APIs to watch a wallet's live activity and summarize it into Markdown and NDJSON outputs. Default target wallet: `0x23cb796cf58bfa12352f0164f479deedbd50658e`.

### Requirements

Install dependencies (Python 3.11+):

```bash
pip install -r requirements.txt
```

### Running the tracker

```bash
python track_polymarket_activity.py --minutes 10 --output-dir polymarket_realtime_output
```

The tracker will:

- Poll both `activity` and `trades` endpoints every 3 seconds, backing off to 5s and 10s on rate limits/errors.
- Append normalized events to `events.ndjson`.
- Track seen event IDs in `state.json` for deduplication.
- Emit `polymarket_realtime_report.md` summarizing the latest events and statistics when the session ends.

Command-line options:

- `--address`: Ethereum address to monitor (defaults to the target wallet above).
- `--minutes`: Duration to watch before finalizing the report (default: 10).
- `--output-dir`: Destination folder for report, event log, and state files (default: `polymarket_realtime_output`).
