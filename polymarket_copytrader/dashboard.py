from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import streamlit as st


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=str, default="output")
    return parser.parse_args()


def read_state(output_dir: Path) -> Dict[str, Any]:
    state_path = output_dir / "dashboard_state.json"
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text())


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)

    st.set_page_config(page_title="Polymarket Copytrader", layout="wide")
    st.title("Polymarket Copytrader Dashboard")

    auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
    refresh_s = st.sidebar.slider("Refresh seconds", 1, 10, 2)

    state = read_state(output_dir)
    if not state:
        st.info("Waiting for data... start app.py to begin.")
    else:
        metrics = state.get("metrics", {})
        positions = state.get("positions", {})
        settings = state.get("settings", {})

        kpi_cols = st.columns(4)
        kpi_cols[0].metric("Total Spent", f"{metrics.get('total_spent', 0):.4f}")
        kpi_cols[1].metric("Total Received", f"{metrics.get('total_received', 0):.4f}")
        kpi_cols[2].metric("Realized PnL", f"{metrics.get('realized_pnl', 0):.4f}")
        kpi_cols[3].metric("Unrealized PnL", f"{metrics.get('unrealized_pnl', 0):.4f}")

        kpi_cols = st.columns(4)
        kpi_cols[0].metric("Total PnL", f"{metrics.get('total_pnl', 0):.4f}")
        kpi_cols[1].metric("Total Fees", f"{metrics.get('total_fees', 0):.4f}")
        kpi_cols[2].metric("Total Volume", f"{metrics.get('total_volume', 0):.4f}")
        kpi_cols[3].metric("Multiplier", f"{settings.get('multiplier', 1.0)}")

        st.subheader("Recent Trades")
        recent = state.get("recent_events", [])
        if recent:
            df = pd.DataFrame(recent)
            st.dataframe(df, use_container_width=True)
        else:
            st.write("No trades yet.")

        st.subheader("Positions")
        if positions:
            rows = []
            for market_id, sides in positions.items():
                for outcome, data in sides.items():
                    rows.append(
                        {
                            "market_id": market_id,
                            "outcome": outcome,
                            "qty": data.get("qty", 0.0),
                            "avg_cost": data.get("avg_cost", 0.0),
                        }
                    )
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

        st.subheader("Risk Settings")
        st.json(settings)

    if auto_refresh:
        time.sleep(refresh_s)
        st.experimental_rerun()


if __name__ == "__main__":
    main()
