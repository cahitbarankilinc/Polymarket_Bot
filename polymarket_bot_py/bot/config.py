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
    free_mode_url: str
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
    trade_event_url_base: str
    tracker_script: Path
    tracker_output_dir: Path
    events_path: Path
    trade_poll_interval_seconds: int

    @staticmethod
    def _get_bool(key: str, default: bool) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_path(key: str) -> Optional[Path]:
        value = os.getenv(key)
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        return Path(value).resolve()

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
        repo_root = Path(__file__).resolve().parents[2]
        tracker_output_dir = (
            Config._get_path("TRACKER_OUTPUT_DIR") or (repo_root / "polymarket_realtime_output").resolve()
        )
        events_path = Config._get_path("EVENTS_NDJSON_PATH") or (tracker_output_dir / "events.ndjson").resolve()
        default_tracker_script = repo_root / "track_polymarket_activity.py"

        return Config(
            home_15m_url=os.getenv("HOME_15M_URL", "https://polymarket.com/crypto/15M"),
            free_mode_url=os.getenv("FREE_MODE_URL", "https://polymarket.com"),
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
            trade_event_url_base=os.getenv("TRADE_EVENT_URL_BASE", "https://polymarket.com/event/"),
            tracker_script=Config._get_path("TRACKER_SCRIPT") or default_tracker_script.resolve(),
            tracker_output_dir=tracker_output_dir,
            events_path=events_path,
            trade_poll_interval_seconds=int(os.getenv("TRADE_POLL_INTERVAL_SECONDS", "60")),
        )
