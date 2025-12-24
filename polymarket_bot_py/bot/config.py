from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from zoneinfo import ZoneInfo


@dataclass
class Config:
    home_15m_url: str
    card_text: str
    side: str
    limit_price_cents: float
    shares: float
    diff_threshold_usd: float
    pause_minutes: int
    timezone: ZoneInfo
    headless: bool
    dry_run: bool
    auto_close_browser: bool
    user_data_dir: Path
    slow_mo_ms: int
    runs_root: Path
    state_path: Path
    events_ndjson_path: Path
    tracker_script_path: Path

    @staticmethod
    def _get_bool(key: str, default: bool) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def load(env_path: Optional[Path] = None) -> "Config":
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()

        side = os.getenv("SIDE", "DOWN").strip().upper()
        if side not in {"UP", "DOWN"}:
            raise ValueError("SIDE must be UP or DOWN")

        limit_price_raw = os.getenv("LIMIT_PRICE_CENTS") or os.getenv("LIMIT_PRICE")
        if not limit_price_raw:
            raise ValueError("LIMIT_PRICE_CENTS or LIMIT_PRICE must be set")

        runs_root = Path(os.getenv("RUNS_ROOT", "./runs")).resolve()
        state_path = Path(os.getenv("STATE_PATH", "./state.json")).resolve()
        events_ndjson_path = Path(
            os.getenv("EVENTS_NDJSON_PATH", "./polymarket_realtime_output/events.ndjson")
        ).resolve()
        tracker_script_path = Path(os.getenv("TRACKER_SCRIPT_PATH", "./track_polymarket_activity.py")).resolve()

        return Config(
            home_15m_url=os.getenv("HOME_15M_URL", "https://polymarket.com/crypto/15M"),
            card_text=os.getenv("CARD_TEXT", "Bitcoin Up or Down - 15 minute"),
            side=side,
            limit_price_cents=float(limit_price_raw),
            shares=float(os.getenv("SHARES", "0")),
            diff_threshold_usd=float(os.getenv("DIFF_THRESHOLD_USD", "100")),
            pause_minutes=int(os.getenv("PAUSE_MINUTES", "60")),
            timezone=ZoneInfo(os.getenv("TIMEZONE", "UTC")),
            headless=Config._get_bool("HEADLESS", True),
            dry_run=Config._get_bool("DRY_RUN", True),
            auto_close_browser=Config._get_bool("AUTO_CLOSE_BROWSER", False),
            user_data_dir=Path(os.getenv("USER_DATA_DIR", "./storage/user_data_dir")).resolve(),
            slow_mo_ms=int(os.getenv("SLOW_MO_MS", "0")),
            runs_root=runs_root,
            state_path=state_path,
            events_ndjson_path=events_ndjson_path,
            tracker_script_path=tracker_script_path,
        )
