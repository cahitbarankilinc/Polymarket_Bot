from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

PRICE_PATTERN = re.compile(r"(\d+)\s*¢")

UTC = ZoneInfo("UTC")


def timestamp_now(timezone: str) -> str:
    try:
        tzinfo = ZoneInfo(timezone)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Invalid timezone %s; falling back to UTC", timezone)
        tzinfo = ZoneInfo("UTC")
    return datetime.now(tzinfo).isoformat()


def current_bucket_close_time_berlin(now_berlin: datetime) -> datetime:
    if now_berlin.tzinfo is None:
        raise ValueError("now_berlin must be timezone-aware")
    bucket_minute = (now_berlin.minute // 15) * 15
    bucket_start = now_berlin.replace(minute=bucket_minute, second=0, microsecond=0)
    return bucket_start + timedelta(minutes=15)


def event_timestamp_from_close_time(close_dt_berlin: datetime) -> int:
    if close_dt_berlin.tzinfo is None:
        raise ValueError("close_dt_berlin must be timezone-aware")
    close_utc = close_dt_berlin.astimezone(UTC)
    return int(close_utc.timestamp())


def parse_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = PRICE_PATTERN.search(text)
    if match:
        return int(match.group(1))
    return None


def most_common_text(samples: Iterable[str]) -> Optional[str]:
    filtered = [s.strip() for s in samples if s and s.strip()]
    if not filtered:
        return None
    counter = Counter(filtered)
    return counter.most_common(1)[0][0]


def append_result_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def safe_event_key(value: str) -> str:
    sanitized = value.strip().replace("\n", " ").replace("|", "-")
    return re.sub(r"\s+", " ", sanitized)
