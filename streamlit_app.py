import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st


METRICS_PATH = Path("output/metrics.json")


st.set_page_config(page_title="Polymarket Copy Trader", layout="wide")

st.title("Polymarket Copy-Trading Dashboard")
# Inspired by /mnt/data/market_watcher.py and /mnt/data/events.ndjson for layout and newest-first display.

refresh_seconds = st.sidebar.number_input("Refresh seconds", min_value=1, max_value=30, value=2)
st_autorefresh = getattr(st, "autorefresh", None)
if callable(st_autorefresh):
    st_autorefresh(interval=refresh_seconds * 1000, key="metrics_refresh")


def _load_metrics() -> dict[str, Any]:
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


metrics = _load_metrics()

if not metrics:
    st.info("Waiting for metrics.json... Run `python main.py` in another terminal.")
    st.stop()

market = metrics.get("market", {})
prices = metrics.get("prices", {})
copy_stats = metrics.get("copier", {})
broker = metrics.get("broker", {})

with st.container():
    st.subheader("Market Status")
    col1, col2, col3 = st.columns(3)
    col1.metric("Market", market.get("question") or "Scanning...")
    col2.metric("Market ID", market.get("market_id") or "-")
    end_time = market.get("end_time")
    remaining = "-"
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
            delta = end_dt - datetime.now(timezone.utc)
            remaining = str(delta).split(".")[0]
        except ValueError:
            remaining = "-"
    col3.metric("Ends In", remaining)

    price_cols = st.columns(2)
    yes_prices = prices.get("yes", {})
    no_prices = prices.get("no", {})
    price_cols[0].metric("YES bid/ask", f"{yes_prices.get('best_bid')} / {yes_prices.get('best_ask')}")
    price_cols[1].metric("NO bid/ask", f"{no_prices.get('best_bid')} / {no_prices.get('best_ask')}")

with st.container():
    st.subheader("Recent Activity (Newest First)")
    events = metrics.get("events", [])
    if events:
        st.dataframe(events, use_container_width=True, height=300)
    else:
        st.write("No recent events yet.")

with st.container():
    st.subheader("Paper Trading KPIs")
    pnl = broker.get("pnl", {})
    positions = broker.get("positions", {})
    latency = copy_stats.get("latency", {})
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Executed", copy_stats.get("executed", 0))
    kpi_cols[1].metric("Missed", copy_stats.get("missed", 0))
    kpi_cols[2].metric("Fill Rate", f"{copy_stats.get('fill_rate', 0.0):.2%}")
    kpi_cols[3].metric("Slippage Avg", f"{copy_stats.get('slippage_avg', 0.0):.6f}")

    kpi_cols = st.columns(4)
    kpi_cols[0].metric("YES Qty", positions.get("YES", {}).get("qty", 0.0))
    kpi_cols[1].metric("YES Avg", positions.get("YES", {}).get("avg_price", 0.0))
    kpi_cols[2].metric("NO Qty", positions.get("NO", {}).get("qty", 0.0))
    kpi_cols[3].metric("NO Avg", positions.get("NO", {}).get("avg_price", 0.0))

    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Total Spent", pnl.get("total_spent", 0.0))
    kpi_cols[1].metric("Total Received", pnl.get("total_received", 0.0))
    kpi_cols[2].metric("Realized PnL", pnl.get("realized", 0.0))
    kpi_cols[3].metric("Unrealized PnL", pnl.get("unrealized", 0.0))

    kpi_cols = st.columns(3)
    kpi_cols[0].metric("Latency Min", latency.get("min", 0.0))
    kpi_cols[1].metric("Latency Avg", latency.get("avg", 0.0))
    kpi_cols[2].metric("Latency Max", latency.get("max", 0.0))

st.caption(f"Last updated: {metrics.get('updated_at')}")
