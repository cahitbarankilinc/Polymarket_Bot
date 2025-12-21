from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _str_to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _str_to_int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


@dataclass
class Config:
    base_dir: Path
    home_15m_url: str
    card_text: str
    timezone: str
    headless: bool
    user_data_dir: Path
    auto_close_browser: bool
    poll_seconds: int
    sample_retries: int
    sample_delay_ms: int
    results_file: Path
    state_file: Path
    screenshot_dir: Path


def load_config() -> Config:
    base_dir = Path(__file__).resolve().parent.parent
    env_path = base_dir / ".env"
    load_dotenv(env_path)

    home_15m_url = os.getenv("HOME_15M_URL", "https://polymarket.com/crypto/15M")
    card_text = os.getenv("CARD_TEXT", "Bitcoin Up or Down - 15 minute")
    timezone = os.getenv("TIMEZONE", "Europe/Istanbul")

    headless = _str_to_bool(os.getenv("HEADLESS"), default=False)
    auto_close_browser = _str_to_bool(os.getenv("AUTO_CLOSE_BROWSER"), default=False)

    poll_seconds = _str_to_int(os.getenv("POLL_SECONDS"), default=15)
    sample_retries = _str_to_int(os.getenv("SAMPLE_RETRIES"), default=3)
    sample_delay_ms = _str_to_int(os.getenv("SAMPLE_DELAY_MS"), default=200)

    user_data_dir = (base_dir / os.getenv("USER_DATA_DIR", "./storage/user_data_dir")).resolve()
    results_file = (base_dir / os.getenv("RESULTS_FILE", "results.txt")).resolve()
    state_file = base_dir / "state.json"
    screenshot_dir = base_dir / "screenshots"

    return Config(
        base_dir=base_dir,
        home_15m_url=home_15m_url,
        card_text=card_text,
        timezone=timezone,
        headless=headless,
        user_data_dir=user_data_dir,
        auto_close_browser=auto_close_browser,
        poll_seconds=poll_seconds,
        sample_retries=sample_retries,
        sample_delay_ms=sample_delay_ms,
        results_file=results_file,
        state_file=state_file,
        screenshot_dir=screenshot_dir,
    )
