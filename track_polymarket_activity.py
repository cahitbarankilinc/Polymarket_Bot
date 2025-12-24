"""
Polymarket real-time activity tracker.

Usage:
    python track_polymarket_activity.py --minutes 0 --output-dir polymarket_realtime_output

The tracker polls Polymarket's public data APIs every 3 seconds to monitor
activity for a configured Ethereum address, keeps a FIFO buffer of the most
recent events, persists a lightweight
`state.json` for deduplication, and emits a `polymarket_realtime_report.md`
summary at exit (or when you stop the process).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import Counter, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

DEFAULT_ADDRESS = "0x23cb796cf58bfa12352f0164f479deedbd50658e"
DEFAULT_MINUTES = 0
POLL_INTERVAL_SECONDS = 3
MAX_EVENTS = 200
ACTIVITY_URL = "https://data-api.polymarket.com/activity"
TRADES_URL = "https://data-api.polymarket.com/trades"


class State:
    def __init__(
        self,
        seen_ids: Optional[Iterable[str]] = None,
        seen_queue: Optional[Iterable[str]] = None,
        last_check: Optional[str] = None,
    ):
        self.seen_ids = set(seen_ids or [])
        self.seen_queue = deque(seen_queue or [])
        self.last_check = last_check

    @classmethod
    def load(cls, path: str) -> "State":
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(raw.get("seen_ids", []), raw.get("seen_queue", []), raw.get("last_check"))
        except Exception:
            # Fall back to empty state on parse error.
            return cls()

    def save(self, path: str) -> None:
        payload = {
            "seen_ids": sorted(self.seen_ids),
            "seen_queue": list(self.seen_queue),
            "last_check": self.last_check,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def track_event_id(self, event_id: str) -> bool:
        if event_id in self.seen_ids:
            return False
        self.seen_ids.add(event_id)
        self.seen_queue.append(event_id)
        while len(self.seen_queue) > MAX_EVENTS:
            oldest = self.seen_queue.popleft()
            self.seen_ids.discard(oldest)
        return True


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def fetch_endpoint(url: str, params: Dict[str, Any], error_log: List[str]) -> Optional[List[Dict[str, Any]]]:
    try:
        resp = requests.get(url, params=params, timeout=15)
    except Exception as exc:
        error_log.append(f"Request error for {url}: {exc}")
        return None

    if resp.status_code >= 500 or resp.status_code == 429:
        error_log.append(f"Backoff triggered for {url}: HTTP {resp.status_code}")
        return None
    if resp.status_code != 200:
        error_log.append(f"Unexpected status {resp.status_code} for {url}")
        return None

    try:
        payload = resp.json()
    except Exception as exc:
        error_log.append(f"JSON parse error for {url}: {exc}")
        return None

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "activities", "trades", "activity"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    error_log.append(f"Unrecognized response format for {url}")
    return None


def generate_event_id(raw: Dict[str, Any], source: str) -> str:
    tx_hash = raw.get("transactionHash") or raw.get("txHash") or raw.get("hash")
    if tx_hash:
        return str(tx_hash)
    event_time = raw.get("timestamp") or raw.get("createdAt") or raw.get("time") or raw.get("eventTime")
    market = raw.get("question") or raw.get("slug") or raw.get("market") or raw.get("marketId")
    side = raw.get("side") or raw.get("action") or ""
    size = raw.get("size") or raw.get("amount") or raw.get("shares") or ""
    return f"{source}:{event_time}|{market}|{side}|{size}"


def normalize_event(raw: Dict[str, Any], source: str, seen_at: str) -> Tuple[str, Dict[str, Any]]:
    event_id = generate_event_id(raw, source)
    event_time = (
        raw.get("timestamp")
        or raw.get("createdAt")
        or raw.get("time")
        or raw.get("eventTime")
    )
    event_type = raw.get("type") or raw.get("eventType") or ("TRADE" if source == "trades" else None)
    side = raw.get("side") or raw.get("action")
    market = (
        raw.get("question")
        or raw.get("slug")
        or raw.get("market")
        or raw.get("marketId")
    )
    outcome = raw.get("outcome") or raw.get("outcomeName") or raw.get("token")
    price = to_float(raw.get("price") or raw.get("avgPrice"))
    size = to_float(raw.get("size") or raw.get("amount") or raw.get("shares"))
    value = to_float(raw.get("value") or raw.get("valueUSD"))
    if value is None and price is not None and size is not None:
        value = round(price * size, 6)
    tx_hash = raw.get("transactionHash") or raw.get("txHash") or raw.get("hash")

    normalized = {
        "seen_at_utc": seen_at,
        "event_time": event_time,
        "type": event_type,
        "side": side,
        "market": market,
        "outcome": outcome,
        "price": price,
        "size": size,
        "value_usd": value,
        "tx_hash": tx_hash,
        "raw_source": source,
    }
    return event_id, normalized


def write_events(path: str, events: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_existing_events(path: str) -> deque[Dict[str, Any]]:
    events: deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)
    if not os.path.exists(path):
        return events
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def compute_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "total_trades": 0,
        "buy_count": 0,
        "sell_count": 0,
        "total_volume": 0.0,
        "volume_events": 0,
        "top_market": None,
    }
    market_counter: Counter = Counter()

    for event in events:
        if event.get("type") == "TRADE":
            summary["total_trades"] += 1
        side = (event.get("side") or "").upper()
        if side == "BUY":
            summary["buy_count"] += 1
        elif side == "SELL":
            summary["sell_count"] += 1
        market = event.get("market")
        if market:
            market_counter[market] += 1
        value = to_float(event.get("value_usd"))
        if value is not None:
            summary["total_volume"] += value
            summary["volume_events"] += 1

    summary["top_market"] = market_counter.most_common(1)[0][0] if market_counter else None
    return summary


def write_report(path: str, address: str, start_time: str, events: List[Dict[str, Any]], errors: List[str]) -> None:
    summary = compute_summary(events)
    recent_events = events[:20]

    lines = []
    lines.append("# Polymarket Real-Time Activity Report")
    lines.append("")
    lines.append(f"Watched address: `{address}`")
    lines.append(f"Session start: {start_time}")
    lines.append(f"Report generated at: {utc_now_iso()}")
    lines.append("")
    lines.append("## Son 20 yeni olay")
    lines.append("")
    headers = [
        "seen_at_utc",
        "event_time",
        "type",
        "side",
        "market",
        "outcome",
        "price",
        "size",
        "value_usd",
        "tx_hash",
        "raw_source",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + " --- |" * len(headers))
    for event in recent_events:
        row = []
        for key in headers:
            value = event.get(key)
            if value is None:
                row.append("")
            else:
                row.append(str(value))
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Özet istatistikler")
    lines.append("")
    lines.append(f"- Toplam trade sayısı: {summary['total_trades']}")
    lines.append(f"- BUY sayısı: {summary['buy_count']}")
    lines.append(f"- SELL sayısı: {summary['sell_count']}")
    volume = round(summary["total_volume"], 6)
    lines.append(f"- Toplam hacim (USD): {volume} ( {summary['volume_events']} olaya göre )")
    lines.append(f"- En sık işlem yapılan market: {summary['top_market'] or 'N/A'}")

    lines.append("")
    lines.append("## Hata & rate limit notları")
    lines.append("")
    if errors:
        for err in errors[-20:]:
            lines.append(f"- {err}")
    else:
        lines.append("- Hiç hata veya rate limit yaşanmadı.")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def poll_events(address: str, minutes: int, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    state_path = os.path.join(output_dir, "state.json")
    events_path = os.path.join(output_dir, "events.ndjson")
    report_path = os.path.join(output_dir, "polymarket_realtime_report.md")

    state = State.load(state_path)
    all_events = load_existing_events(events_path)
    error_log: List[str] = []

    start_time = utc_now_iso()
    end_time = time.time() + minutes * 60 if minutes > 0 else None

    while end_time is None or time.time() < end_time:
        params = {"user": address, "limit": 50, "offset": 0}
        activity = fetch_endpoint(ACTIVITY_URL, params, error_log)
        trades = fetch_endpoint(TRADES_URL, params, error_log)

        new_events: List[Dict[str, Any]] = []
        seen_at = utc_now_iso()

        for payload, source in ((activity, "activity"), (trades, "trades")):
            if not payload:
                continue
            for item in payload:
                event_id, normalized = normalize_event(item, source, seen_at)
                if not state.track_event_id(event_id):
                    continue
                new_events.append(normalized)

        if new_events:
            for event in reversed(new_events):
                all_events.appendleft(event)
            write_events(events_path, all_events)

        state.last_check = utc_now_iso()
        state.save(state_path)

        time.sleep(POLL_INTERVAL_SECONDS)

    write_report(report_path, address, start_time, list(all_events), error_log)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track Polymarket activity for a wallet")
    parser.add_argument("--address", default=DEFAULT_ADDRESS, help="Ethereum address to track")
    parser.add_argument(
        "--minutes",
        type=int,
        default=DEFAULT_MINUTES,
        help="How many minutes to monitor before finalizing the report (0 = run until stopped)",
    )
    parser.add_argument(
        "--output-dir",
        default="polymarket_realtime_output",
        help="Directory for report, event log, and state",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    poll_events(args.address, args.minutes, args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
