from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

DEFAULT_OUTPUT_DIR = os.path.join(os.getcwd(), "output")
SESSION_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "session.json")


@dataclass
class AppConfig:
    watched_address: str = ""
    individual_share_rate: float = 1.0
    poll_interval_seconds: int = 1
    max_events_buffer: int = 200
    dashboard_refresh_seconds: int = 1
    order_ttl_seconds: int = 10
    slippage_enabled: bool = False
    slippage_bps: float = 0.0
    replay_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_output_dir() -> str:
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    return DEFAULT_OUTPUT_DIR


def load_session_config(path: str = SESSION_PATH) -> AppConfig:
    ensure_output_dir()
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return AppConfig(**payload)
    except Exception:
        return AppConfig()


def save_session_config(config: AppConfig, path: str = SESSION_PATH) -> None:
    ensure_output_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)
