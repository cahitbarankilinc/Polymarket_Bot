from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

PRICE_PATTERN = re.compile(r"(\d+)\s*¢")


def timestamp_now(timezone: str) -> str:
    try:
        tzinfo = ZoneInfo(timezone)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Invalid timezone %s; falling back to UTC", timezone)
        tzinfo = ZoneInfo("UTC")
    return datetime.now(tzinfo).isoformat()


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
