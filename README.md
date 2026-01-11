# Polymarket Copy-Trading Simulator (Paper Trading)

A fully async, paper-only bot that monitors a Polymarket Ethereum address, discovers the active 15-minute Bitcoin market, subscribes to live YES/NO prices, and simulates copy trades with limit-fill logic.

## Features
- **Activity polling** (every second) from Polymarket public APIs
- **Deduped events** persisted to `output/state.json`
- **Newest-first dashboard** for live market and address activity
- **Copy trade simulation** with limit price and TTL
- **Paper portfolio** tracking positions, averages, and PnL
- **Replay mode** for offline testing from NDJSON

## Installation
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
python main.py --watched-address 0xYOURADDRESS --individual-share-rate 0.1
```

Interactive input also works if flags are omitted:
```bash
python main.py
```

Optional slippage model (basis points, default 0):
```bash
python main.py --watched-address 0xYOURADDRESS --individual-share-rate 0.1 --slippage-bps 5
```

## Replay mode
```bash
python main.py --watched-address 0xYOURADDRESS --individual-share-rate 0.1 --replay-path output/events.ndjson
```

## Output files
- `output/events.ndjson` — normalized address activity events
- `output/paper_trades.ndjson` — executed/missed paper trades
- `output/state.json` — dedup state
- `output/session.json` — session inputs + timestamps

## Notes
- This project **does not** place real trades or require private keys.
- It is strictly a simulation to measure copy-trade fill feasibility.
