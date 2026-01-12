# Polymarket Copy Trader (Paper)

This project provides a **paper trading** copy engine for Polymarket wallet activity. It polls the public activity/trades APIs, discovers the active 15-minute Bitcoin market, subscribes to the CLOB WebSocket for live prices, and simulates limit fills with a TTL. The dashboard is a Streamlit UI powered by a lightweight local REST API.

> ⚠️ **No real trades.** There are no private keys or signing. This is a simulation only.

## Features

- Polls wallet activity every second with dedup + NDJSON logging.
- Discovers active 15-minute BTC markets and refreshes at 00/15/30/45.
- Live YES/NO best bid/ask via WebSocket.
- Paper copy engine with limit + TTL fill simulation.
- KPI tracking (fill rate, PnL, latency, slippage).
- Streamlit dashboard UI.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (recommended)

Launch the Streamlit dashboard (it will start the backend automatically):

```bash
streamlit run app/ui_streamlit.py
```

Then set your configuration in the sidebar (watched address + rate required).

## Run Backend Separately (optional)

```bash
python -m app.main
```

In this mode, keep the backend running and open the UI in another terminal:

```bash
streamlit run app/ui_streamlit.py
```

## Output Files

All runtime files are created under `output/`:

- `output/events.ndjson` – normalized activity/trade events.
- `output/paper_trades.ndjson` – order lifecycle events.
- `output/state.json` – dedup state.
- `output/session.json` – Streamlit config.

## Replay Mode (optional)

Set `replay_path` in `output/session.json` to point at an NDJSON file. When `replay_path` is set, live polling is disabled and the file is replayed into the copier.

## Notes

- Terminal output is minimal (start, market change, reconnects).
- Streamlit auto-refresh is controlled by `dashboard_refresh_seconds`.
