"""
Polymarket activity calculator for the last 7 days.

Usage:
    python Hesaplayici.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

ACTIVITY_URL = "https://data-api.polymarket.com/activity"
DEFAULT_LIMIT = 500
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


def _init_stats() -> Dict[str, float]:
    return {"size": 0.0, "value_usd": 0.0, "event_count": 0.0}


def _extract_size(event: Dict[str, Any]) -> Optional[float]:
    return to_float(event.get("size") or event.get("amount") or event.get("shares"))


def _extract_price(event: Dict[str, Any]) -> Optional[float]:
    return to_float(event.get("price") or event.get("avgPrice"))


def _extract_value_usd(event: Dict[str, Any], size: Optional[float], price: Optional[float]) -> Optional[float]:
    value_usd = to_float(
        event.get("value_usd")
        or event.get("valueUSD")
        or event.get("valueUsd")
        or event.get("value")
        or event.get("amountUSD")
        or event.get("amountUsd")
    )
    if value_usd is None and size is not None and price is not None:
        value_usd = price * size
    return value_usd


def _update_stats(stats: Dict[str, float], event: Dict[str, Any]) -> None:
    size = _extract_size(event)
    price = _extract_price(event)
    value_usd = _extract_value_usd(event, size, price)
    stats["event_count"] += 1.0
    if size is not None:
        stats["size"] += size
    if value_usd is not None:
        stats["value_usd"] += value_usd


def _finalize_row(day_key: str, stats: Dict[str, float]) -> Dict[str, Any]:
    return {
        "date": day_key,
        "event_count": int(stats["event_count"]),
        "total_size": round(stats["size"], 6),
        "total_value_usd": round(stats["value_usd"], 6),
    }


def _print_day_summary(row: Dict[str, Any]) -> None:
    print(f"\nGun tamamlandi: {row['date']}")
    print(f"- Islem sayisi: {row['event_count']}")
    print(f"- Toplam size: {row['total_size']}")
    print(f"- Toplam value (USD): {row['total_value_usd']}")


def fetch_activity(address: str, error_log: List[str]) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    rows: List[Dict[str, Any]] = []
    overall_stats = _init_stats()
    offset = 0
    page = 0
    total_items = 0
    cutoff = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=7)
    current_day: Optional[str] = None
    current_stats = _init_stats()
    session = requests.Session()

    while True:
        params = {"user": address, "limit": DEFAULT_LIMIT, "offset": offset}
        try:
            resp = session.get(ACTIVITY_URL, params=params, timeout=15)
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

        page += 1
        total_items += len(payload)
        progress_day = current_day or "-"
        print(
            f"Veri cekiliyor... sayfa: {page}, offset: {offset}, "
            f"toplam eleman: {total_items}, aktif gun: {progress_day}"
        )
        sys.stdout.flush()

        for item in payload:
            event_time = parse_event_time(item)
            if event_time is None:
                continue
            if event_time < cutoff:
                if current_day is not None:
                    row = _finalize_row(current_day, current_stats)
                    rows.append(row)
                    _print_day_summary(row)
                return rows, overall_stats
            day_key = event_time.date().isoformat()
            if current_day is None:
                current_day = day_key
            elif day_key != current_day:
                row = _finalize_row(current_day, current_stats)
                rows.append(row)
                _print_day_summary(row)
                current_day = day_key
                current_stats = _init_stats()

            _update_stats(current_stats, item)
            _update_stats(overall_stats, item)

        offset += DEFAULT_LIMIT

    if current_day is not None:
        row = _finalize_row(current_day, current_stats)
        rows.append(row)
        _print_day_summary(row)

    return rows, overall_stats


def summarize_by_day(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: Dict[str, Dict[str, float]] = {}

    for event in events:
        event_time = parse_event_time(event)
        if event_time is None:
            continue
        day_key = event_time.date().isoformat()
        if day_key not in summary:
            summary[day_key] = {"size": 0.0, "value_usd": 0.0, "event_count": 0.0}

        size = _extract_size(event)
        price = _extract_price(event)
        value_usd = _extract_value_usd(event, size, price)
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


def build_report(
    address: str,
    rows: List[Dict[str, Any]],
    overall_stats: Dict[str, float],
    errors: List[str],
) -> str:
    overall_row = _finalize_row("GENEL", overall_stats)
    lines = []
    lines.append("# Hesaplayici - Son 7 Gün Aktivite Özeti")
    lines.append("")
    lines.append(f"Adres: `{address}`")
    lines.append(f"Rapor zamanı (UTC): {dt.datetime.now(tz=dt.timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Genel Durum")
    lines.append("")
    lines.append(f"- Toplam islem sayisi: {overall_row['event_count']}")
    lines.append(f"- Toplam size: {overall_row['total_size']}")
    lines.append(f"- Toplam value (USD): {overall_row['total_value_usd']}")
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
    rows, overall_stats = fetch_activity(address, errors)
    report = build_report(address, rows, overall_stats, errors)

    print("\nTum gunler tamamlandi. Genel durum:")
    print(f"- Toplam islem sayisi: {int(overall_stats['event_count'])}")
    print(f"- Toplam size: {round(overall_stats['size'], 6)}")
    print(f"- Toplam value (USD): {round(overall_stats['value_usd'], 6)}")
    print(report)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nRapor '{OUTPUT_FILE}' dosyasina kaydedildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
