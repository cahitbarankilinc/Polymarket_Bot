"""
Polymarket activity calculator for the last 7 days.

Usage:
    python Hesaplayici.py
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, Iterable, List, Optional

import requests

ACTIVITY_URL = "https://data-api.polymarket.com/activity"
DEFAULT_LIMIT = 100
OUTPUT_FILE = "hesaplayici_output.md"


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def parse_event_time(raw: Dict[str, Any]) -> Optional[dt.datetime]:
    event_time = raw.get("timestamp") or raw.get("createdAt") or raw.get("time") or raw.get("eventTime")
    if event_time is None:
        return None
    if isinstance(event_time, (int, float)):
        timestamp = float(event_time)
        if timestamp > 1e12:
            timestamp /= 1000.0
        return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
    if isinstance(event_time, str):
        try:
            normalized = event_time.replace("Z", "+00:00")
            parsed = dt.datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            return None
    return None


def fetch_activity(address: str, error_log: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    offset = 0
    cutoff = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=7)

    while True:
        params = {"user": address, "limit": DEFAULT_LIMIT, "offset": offset}
        try:
            resp = requests.get(ACTIVITY_URL, params=params, timeout=15)
        except Exception as exc:
            error_log.append(f"Request error: {exc}")
            break

        if resp.status_code != 200:
            error_log.append(f"Unexpected status {resp.status_code}")
            break

        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            error_log.append(f"JSON parse error: {exc}")
            break

        if isinstance(payload, dict):
            for key in ("data", "activities", "activity"):
                if key in payload and isinstance(payload[key], list):
                    payload = payload[key]
                    break

        if not isinstance(payload, list):
            error_log.append("Unrecognized response format")
            break

        if not payload:
            break

        for item in payload:
            event_time = parse_event_time(item)
            if event_time is None:
                continue
            if event_time < cutoff:
                return results
            results.append(item)

        offset += DEFAULT_LIMIT

    return results


def summarize_by_day(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: Dict[str, Dict[str, float]] = {}

    for event in events:
        event_time = parse_event_time(event)
        if event_time is None:
            continue
        day_key = event_time.date().isoformat()
        if day_key not in summary:
            summary[day_key] = {"size": 0.0, "value_usd": 0.0, "event_count": 0.0}

        size = to_float(event.get("size") or event.get("amount") or event.get("shares"))
        value_usd = to_float(event.get("value_usd") or event.get("valueUSD") or event.get("value"))
        summary[day_key]["event_count"] += 1.0
        if size is not None:
            summary[day_key]["size"] += size
        if value_usd is not None:
            summary[day_key]["value_usd"] += value_usd

    ordered_days = sorted(summary.keys(), reverse=True)
    rows = []
    for day in ordered_days:
        rows.append(
            {
                "date": day,
                "event_count": int(summary[day]["event_count"]),
                "total_size": round(summary[day]["size"], 6),
                "total_value_usd": round(summary[day]["value_usd"], 6),
            }
        )
    return rows


def build_report(address: str, rows: List[Dict[str, Any]], errors: List[str]) -> str:
    lines = []
    lines.append("# Hesaplayici - Son 7 Gün Aktivite Özeti")
    lines.append("")
    lines.append(f"Adres: `{address}`")
    lines.append(f"Rapor zamanı (UTC): {dt.datetime.now(tz=dt.timezone.utc).isoformat()}")
    lines.append("")
    lines.append("| Gün | İşlem Sayısı | Toplam Size | Toplam Value (USD) |")
    lines.append("| --- | --- | --- | --- |")
    if rows:
        for row in rows:
            lines.append(
                f"| {row['date']} | {row['event_count']} | {row['total_size']} | {row['total_value_usd']} |"
            )
    else:
        lines.append("| - | 0 | 0 | 0 |")

    lines.append("")
    lines.append("## Hata Notları")
    lines.append("")
    if errors:
        for error in errors:
            lines.append(f"- {error}")
    else:
        lines.append("- Hata yok.")

    return "\n".join(lines)


def main() -> int:
    address = input("Lutfen Polymarket adresini girin: ").strip()
    if not address:
        print("Adres girilmedi. Cikis yapiliyor.")
        return 1

    errors: List[str] = []
    events = fetch_activity(address, errors)
    rows = summarize_by_day(events)
    report = build_report(address, rows, errors)

    print(report)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nRapor '{OUTPUT_FILE}' dosyasina kaydedildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
