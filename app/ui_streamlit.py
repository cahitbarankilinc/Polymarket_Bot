from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict

import os

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.config import AppConfig, load_session_config

DEFAULT_API_HOST = os.environ.get("POLY_API_HOST", "localhost")
DEFAULT_API_PORT = int(os.environ.get("POLY_API_PORT", "8765"))


def _start_backend(host: str, port: int, force: bool = False) -> None:
    if st.session_state.get("backend_started") and not force:
        return
    env = os.environ.copy()
    env["POLY_API_HOST"] = host
    env["POLY_API_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    st.session_state["backend_started"] = True
    st.session_state["backend_pid"] = process.pid
    st.session_state["backend_host"] = host
    st.session_state["backend_port"] = port


def _api_url(host: str, port: int) -> str:
    client_host = "localhost" if host in {"0.0.0.0", "::"} else host
    return f"http://{client_host}:{port}"


def _get_json(host: str, port: int, path: str) -> Dict[str, Any]:
    resp = requests.get(f"{_api_url(host, port)}{path}", timeout=5)
    resp.raise_for_status()
    return resp.json()


def _post_json(host: str, port: int, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.post(f"{_api_url(host, port)}{path}", json=payload, timeout=5)
    resp.raise_for_status()
    return resp.json()


def _wait_for_backend(host: str, port: int, timeout_s: float = 8.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = requests.get(f"{_api_url(host, port)}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _time_remaining(end_time: str | None) -> str:
    end_dt = _parse_time(end_time)
    if not end_dt:
        return "N/A"
    remaining = end_dt - datetime.now(timezone.utc)
    return f"{int(remaining.total_seconds())}s"


st.set_page_config(page_title="Polymarket Copy Trader", layout="wide")

session_config = load_session_config()

with st.sidebar:
    st.title("Copy Trader Config")
    watched_address = st.text_input("watched_address", session_config.watched_address)
    share_rate = st.number_input("individual_share_rate", min_value=0.0, value=session_config.individual_share_rate)
    poll_interval = st.number_input("poll_interval_seconds", min_value=1, value=session_config.poll_interval_seconds)
    max_events = st.number_input("max_events_buffer", min_value=50, value=session_config.max_events_buffer)
    refresh_seconds = st.number_input("dashboard_refresh_seconds", min_value=1, value=session_config.dashboard_refresh_seconds)
    order_ttl = st.number_input("order_ttl_seconds", min_value=1, value=session_config.order_ttl_seconds)
    slippage_enabled = st.checkbox("slippage_enabled", value=session_config.slippage_enabled)
    slippage_bps = st.number_input("slippage_bps", min_value=0.0, value=session_config.slippage_bps)
    api_host = st.text_input("api_host", session_config.api_host or DEFAULT_API_HOST)
    api_port = st.number_input("api_port", min_value=1024, value=session_config.api_port or DEFAULT_API_PORT)
    if api_host.strip() in {"0.0.0.0", "::"}:
        st.caption("macOS için istemci erişimi localhost üzerinden yapılır; 0.0.0.0 sadece bind içindir.")

    if st.button("Apply"):
        apply_host = api_host.strip() or DEFAULT_API_HOST
        apply_port = int(api_port)
        _start_backend(apply_host, apply_port)
        if not _wait_for_backend(apply_host, apply_port):
            _start_backend(apply_host, apply_port, force=True)
        if not _wait_for_backend(apply_host, apply_port):
            st.error("Backend başlatılamadı veya /health erişilemedi. Port çakışması olabilir.")
            st.stop()
        config = AppConfig(
            watched_address=watched_address.strip(),
            individual_share_rate=float(share_rate),
            poll_interval_seconds=int(poll_interval),
            max_events_buffer=int(max_events),
            dashboard_refresh_seconds=int(refresh_seconds),
            order_ttl_seconds=int(order_ttl),
            slippage_enabled=slippage_enabled,
            slippage_bps=float(slippage_bps),
            replay_path=None,
            api_host=apply_host,
            api_port=apply_port,
        )
        try:
            _post_json(config.api_host, config.api_port, "/config", config.to_dict())
            st.success("Config updated")
        except Exception as exc:
            st.error(f"Config update failed: {exc}")
    if not watched_address:
        st.warning("watched_address boş. Copy orders oluşması için adres girip Apply yapın.")


autorefresh_interval = int(refresh_seconds) * 1000
st_autorefresh(interval=autorefresh_interval, key="dashboard_refresh")

connection_ok = True
try:
    api_host = session_config.api_host or DEFAULT_API_HOST
    api_port = session_config.api_port or DEFAULT_API_PORT
    state = _get_json(api_host, api_port, "/state")
except Exception:
    connection_ok = False
    _start_backend(api_host, api_port)
    if not _wait_for_backend(api_host, api_port):
        _start_backend(api_host, api_port, force=True)
    if not _wait_for_backend(api_host, api_port):
        st.warning("Backend henüz hazır değil veya erişilemiyor. Lütfen portu kontrol edin.")
        state = {}
    else:
        state = _get_json(api_host, api_port, "/state")

header = st.container()

with header:
    market = state.get("market", {})
    st.subheader("Market")
    st.write(
        {
            "name": market.get("market_name"),
            "market_id": market.get("market_id"),
            "end_time": market.get("end_time"),
            "countdown": _time_remaining(market.get("end_time")),
            "connection": "online" if connection_ok else "starting",
        }
    )

price_cols = st.columns(2)
price_cache = state.get("price_cache", {})
for idx, side in enumerate(["YES", "NO"]):
    snapshot = price_cache.get(side, {})
    with price_cols[idx]:
        st.metric(
            f"{side} Best Bid",
            snapshot.get("best_bid"),
        )
        st.metric(
            f"{side} Best Ask",
            snapshot.get("best_ask"),
        )
        st.caption(f"Last update: {snapshot.get('last_update_utc')}")

cols = st.columns(2)

with cols[0]:
    st.subheader("Watched Address Events")
    try:
        events = _get_json(api_host, api_port, "/events?limit=20").get("events", [])
    except Exception:
        events = []
    st.dataframe(events, use_container_width=True, hide_index=True)

with cols[1]:
    st.subheader("Copy Orders")
    try:
        orders = _get_json(api_host, api_port, "/orders?limit=50").get("orders", [])
    except Exception:
        orders = []
    st.dataframe(orders, use_container_width=True, hide_index=True)

st.subheader("KPIs")
paper = state.get("paper", {})
stats = paper.get("stats", {})
fill_rate = None
if stats.get("total_trades_executed") is not None:
    executed = stats.get("total_trades_executed", 0)
    missed = stats.get("total_trades_missed", 0)
    denom = executed + missed
    fill_rate = executed / denom if denom else 0.0

kpi_cols = st.columns(4)
kpi_cols[0].metric("Source Trades", stats.get("total_trades_source"))
kpi_cols[1].metric("Orders Created", stats.get("total_orders_created"))
kpi_cols[2].metric("Fill Rate", fill_rate)
kpi_cols[3].metric("Realized PnL", paper.get("realized_pnl_usd"))

pnl_cols = st.columns(3)
mark_prices = {
    "YES": price_cache.get("YES", {}).get("mid"),
    "NO": price_cache.get("NO", {}).get("mid"),
}

unrealized = paper.get("unrealized_pnl_usd")
if unrealized is None:
    unrealized = 0.0

pnl_cols[0].metric("Cash Spent", paper.get("cash_spent_usd"))
pnl_cols[1].metric("Cash Received", paper.get("cash_received_usd"))
pnl_cols[2].metric("Unrealized PnL", unrealized)

latency_samples = stats.get("latency_samples", [])
if latency_samples:
    st.line_chart(latency_samples, height=200)
