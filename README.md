# Polymarket Copy Trader (Paper)

This project provides a **paper trading** copy engine for Polymarket wallet activity. It polls the public activity/trades APIs, discovers the active 15-minute Bitcoin market, subscribes to the CLOB WebSocket for live prices, and simulates limit fills with a TTL. The dashboard is a lightweight HTML UI powered by a local REST API.

> ⚠️ **No real trades.** There are no private keys or signing. This is a simulation only.

## Features

- Polls wallet activity every second with dedup + NDJSON logging.
- Discovers active 15-minute BTC markets and refreshes at 00/15/30/45.
- Live YES/NO best bid/ask via WebSocket.
- Paper copy engine with limit + TTL fill simulation.
- KPI tracking (fill rate, PnL, latency, slippage).
- HTML dashboard UI.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (recommended)

Start the backend API server:

```bash
python -m app.main
```

Open the dashboard in your browser:

```
http://localhost:8765/
```

Then set your configuration in the form (watched address + rate required).

If you see an error like `address already in use`, either stop the existing backend process or set a different port via `POLY_API_PORT`.

## Output Files

All runtime files are created under `output/`:

- `output/events.ndjson` – normalized activity/trade events.
- `output/paper_trades.ndjson` – order lifecycle events.
- `output/state.json` – dedup state.
- `output/session.json` – Dashboard config.

## Replay Mode (optional)

Set `replay_path` in `output/session.json` to point at an NDJSON file. When `replay_path` is set, live polling is disabled and the file is replayed into the copier.

## Notes

- Terminal output is minimal (start, market change, reconnects).
- Dashboard auto-refresh is controlled by `dashboard_refresh_seconds`.
