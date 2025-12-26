"""
Polymarket activity calculator for the last 24 hours.

Usage:
    python Hesaplayici.py
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

ACTIVITY_URL = "https://data-api.polymarket.com/activity"
DEFAULT_LIMIT = 250
OUTPUT_FILE = "hesaplayici_output.md"
HOURS_WINDOW = 24


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


def _init_stats() -> Dict[str, Optional[float]]:
    return {
        "size": 0.0,
        "value_usd": 0.0,
        "event_count": 0.0,
        "min_size": None,
        "max_size": None,
        "min_value_usd": None,
        "max_value_usd": None,
    }


def _extract_size(event: Dict[str, Any]) -> Optional[float]:
    return to_float(event.get("size") or event.get("amount") or event.get("shares"))


def _extract_value_usd(event: Dict[str, Any], size: Optional[float] = None) -> Optional[float]:
    value_usd = to_float(
        event.get("value_usd")
        or event.get("valueUSD")
        or event.get("valueUsd")
        or event.get("value")
        or event.get("usdValue")
        or event.get("usd_value")
        or event.get("amountUSD")
        or event.get("amountUsd")
        or event.get("collateralValue")
    )
    if value_usd is not None:
        return value_usd
    price = to_float(event.get("price") or event.get("avgPrice"))
    size = size if size is not None else _extract_size(event)
    if price is not None and size is not None:
        return price * size
    return None


def _update_stats(stats: Dict[str, Optional[float]], event: Dict[str, Any]) -> None:
    size = _extract_size(event)
    value_usd = _extract_value_usd(event, size=size)
    stats["event_count"] = (stats["event_count"] or 0.0) + 1.0
    if size is not None:
        stats["size"] = (stats["size"] or 0.0) + size
        stats["min_size"] = size if stats["min_size"] is None else min(stats["min_size"], size)
        stats["max_size"] = size if stats["max_size"] is None else max(stats["max_size"], size)
    if value_usd is not None:
        stats["value_usd"] = (stats["value_usd"] or 0.0) + value_usd
        stats["min_value_usd"] = (
            value_usd if stats["min_value_usd"] is None else min(stats["min_value_usd"], value_usd)
        )
        stats["max_value_usd"] = (
            value_usd if stats["max_value_usd"] is None else max(stats["max_value_usd"], value_usd)
        )


def _finalize_row(period_key: str, stats: Dict[str, Optional[float]]) -> Dict[str, Any]:
    return {
        "date": period_key,
        "event_count": int(stats["event_count"] or 0.0),
        "total_size": round(stats["size"] or 0.0, 6),
        "total_value_usd": round(stats["value_usd"] or 0.0, 6),
        "min_size": round(stats["min_size"], 6) if stats["min_size"] is not None else None,
        "max_size": round(stats["max_size"], 6) if stats["max_size"] is not None else None,
        "min_value_usd": round(stats["min_value_usd"], 6) if stats["min_value_usd"] is not None else None,
        "max_value_usd": round(stats["max_value_usd"], 6) if stats["max_value_usd"] is not None else None,
    }


def _print_day_summary(row: Dict[str, Any]) -> None:
    print(f"\nSaat tamamlandi: {row['date']}")
    print(f"- Islem sayisi: {row['event_count']}")
    print(f"- Toplam size: {row['total_size']}")
    print(f"- Toplam value (USD): {row['total_value_usd']}")
    print(f"- Min size: {row['min_size'] if row['min_size'] is not None else 'N/A'}")
    print(f"- Max size: {row['max_size'] if row['max_size'] is not None else 'N/A'}")
    print(f"- Min value (USD): {row['min_value_usd'] if row['min_value_usd'] is not None else 'N/A'}")
    print(f"- Max value (USD): {row['max_value_usd'] if row['max_value_usd'] is not None else 'N/A'}")


def _print_progress(total_events: int, offset: int, current_hour: Optional[str]) -> None:
    hour_label = current_hour or "-"
    print(
        f"\rKonum: offset={offset} | Aktif saat: {hour_label} | Cekilen veri sayisi: {total_events}",
        end="",
        flush=True,
    )


def fetch_activity(address: str, error_log: List[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Optional[float]]]:
    rows: List[Dict[str, Any]] = []
    overall_stats = _init_stats()
    offset = 0
    cutoff = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=HOURS_WINDOW)
    current_hour: Optional[str] = None
    current_stats = _init_stats()
    total_events = 0
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

        for item in payload:
            total_events += 1
            event_time = parse_event_time(item)
            if event_time is None:
                continue
            if event_time < cutoff:
                if current_hour is not None:
                    row = _finalize_row(current_hour, current_stats)
                    rows.append(row)
                    _print_day_summary(row)
                return rows, overall_stats
            hour_key = event_time.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00 UTC")
            if current_hour is None:
                current_hour = hour_key
            elif hour_key != current_hour:
                row = _finalize_row(current_hour, current_stats)
                rows.append(row)
                _print_day_summary(row)
                current_hour = hour_key
                current_stats = _init_stats()

            _update_stats(current_stats, item)
            _update_stats(overall_stats, item)

        offset += DEFAULT_LIMIT
        _print_progress(total_events, offset, current_hour)

    if total_events:
        print("")
    if current_hour is not None:
        row = _finalize_row(current_hour, current_stats)
        rows.append(row)
        _print_day_summary(row)

    return rows, overall_stats


def summarize_by_day(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: Dict[str, Dict[str, Optional[float]]] = {}

    for event in events:
        event_time = parse_event_time(event)
        if event_time is None:
            continue
        hour_key = event_time.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00 UTC")
        if hour_key not in summary:
            summary[hour_key] = _init_stats()

        size = _extract_size(event)
        value_usd = _extract_value_usd(event, size=size)
        summary[hour_key]["event_count"] = (summary[hour_key]["event_count"] or 0.0) + 1.0
        if size is not None:
            summary[hour_key]["size"] = (summary[hour_key]["size"] or 0.0) + size
            summary[hour_key]["min_size"] = (
                size
                if summary[hour_key]["min_size"] is None
                else min(summary[hour_key]["min_size"], size)
            )
            summary[hour_key]["max_size"] = (
                size
                if summary[hour_key]["max_size"] is None
                else max(summary[hour_key]["max_size"], size)
            )
        if value_usd is not None:
            summary[hour_key]["value_usd"] = (summary[hour_key]["value_usd"] or 0.0) + value_usd
            summary[hour_key]["min_value_usd"] = (
                value_usd
                if summary[hour_key]["min_value_usd"] is None
                else min(summary[hour_key]["min_value_usd"], value_usd)
            )
            summary[hour_key]["max_value_usd"] = (
                value_usd
                if summary[hour_key]["max_value_usd"] is None
                else max(summary[hour_key]["max_value_usd"], value_usd)
            )

    ordered_days = sorted(summary.keys(), reverse=True)
    rows = []
    for day in ordered_days:
        rows.append(
            {
                "date": day,
                "event_count": int(summary[day]["event_count"] or 0.0),
                "total_size": round(summary[day]["size"] or 0.0, 6),
                "total_value_usd": round(summary[day]["value_usd"] or 0.0, 6),
                "min_size": round(summary[day]["min_size"], 6) if summary[day]["min_size"] is not None else None,
                "max_size": round(summary[day]["max_size"], 6) if summary[day]["max_size"] is not None else None,
                "min_value_usd": (
                    round(summary[day]["min_value_usd"], 6) if summary[day]["min_value_usd"] is not None else None
                ),
                "max_value_usd": (
                    round(summary[day]["max_value_usd"], 6) if summary[day]["max_value_usd"] is not None else None
                ),
            }
        )
    return rows


def build_report(
    address: str,
    rows: List[Dict[str, Any]],
    overall_stats: Dict[str, Optional[float]],
    errors: List[str],
) -> str:
    overall_row = _finalize_row("GENEL", overall_stats)
    lines = []
    lines.append("# Hesaplayici - Son 24 Saat Aktivite Özeti")
    lines.append("")
    lines.append(f"Adres: `{address}`")
    lines.append(f"Rapor zamanı (UTC): {dt.datetime.now(tz=dt.timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Genel Durum")
    lines.append("")
    lines.append(f"- Toplam islem sayisi: {overall_row['event_count']}")
    lines.append(f"- Toplam size: {overall_row['total_size']}")
    lines.append(f"- Toplam value (USD): {overall_row['total_value_usd']}")
    lines.append(f"- Min size: {overall_row['min_size'] if overall_row['min_size'] is not None else 'N/A'}")
    lines.append(f"- Max size: {overall_row['max_size'] if overall_row['max_size'] is not None else 'N/A'}")
    lines.append(
        f"- Min value (USD): {overall_row['min_value_usd'] if overall_row['min_value_usd'] is not None else 'N/A'}"
    )
    lines.append(
        f"- Max value (USD): {overall_row['max_value_usd'] if overall_row['max_value_usd'] is not None else 'N/A'}"
    )
    lines.append("")
    lines.append(
        "| Saat | İşlem Sayısı | Toplam Size | Toplam Value (USD) | Min Size | Max Size | Min Value (USD) | Max Value (USD) |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    if rows:
        for row in rows:
            lines.append(
                "| {date} | {event_count} | {total_size} | {total_value_usd} | {min_size} | {max_size} | "
                "{min_value_usd} | {max_value_usd} |".format(
                    date=row["date"],
                    event_count=row["event_count"],
                    total_size=row["total_size"],
                    total_value_usd=row["total_value_usd"],
                    min_size=row["min_size"] if row["min_size"] is not None else "N/A",
                    max_size=row["max_size"] if row["max_size"] is not None else "N/A",
                    min_value_usd=row["min_value_usd"] if row["min_value_usd"] is not None else "N/A",
                    max_value_usd=row["max_value_usd"] if row["max_value_usd"] is not None else "N/A",
                )
            )
    else:
        lines.append("| - | 0 | 0 | 0 | N/A | N/A | N/A | N/A |")

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

    print("\nTum saatler tamamlandi. Genel durum:")
    print(f"- Toplam islem sayisi: {int(overall_stats['event_count'] or 0.0)}")
    print(f"- Toplam size: {round(overall_stats['size'] or 0.0, 6)}")
    print(f"- Toplam value (USD): {round(overall_stats['value_usd'] or 0.0, 6)}")
    print(f"- Min size: {overall_stats['min_size'] if overall_stats['min_size'] is not None else 'N/A'}")
    print(f"- Max size: {overall_stats['max_size'] if overall_stats['max_size'] is not None else 'N/A'}")
    print(f"- Min value (USD): {overall_stats['min_value_usd'] if overall_stats['min_value_usd'] is not None else 'N/A'}")
    print(f"- Max value (USD): {overall_stats['max_value_usd'] if overall_stats['max_value_usd'] is not None else 'N/A'}")
    print(report)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nRapor '{OUTPUT_FILE}' dosyasina kaydedildi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
