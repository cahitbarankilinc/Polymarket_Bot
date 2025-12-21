from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple


def setup_run_directory(base: Path, tzinfo) -> Tuple[Path, Path]:
    now = datetime.now(tzinfo)
    day_dir = base / now.strftime("%Y%m%d")
    run_dir = day_dir / now.strftime("%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "log.txt"
    return run_dir, log_path


def configure_logging(log_path: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def bucket_key(now: datetime) -> str:
    bucket_minute = (now.minute // 15) * 15
    return now.strftime("%Y%m%d%H") + f"{bucket_minute:02d}"


def safe_float_from_text(text: str) -> float:
    digits = "".join(ch for ch in text if ch.isdigit() or ch in {".", ","})
    if not digits:
        raise ValueError("Could not parse float from text")
    normalized = digits.replace(",", "")
    return float(normalized)

