from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class BotState:
    last_bucket_key: Optional[str] = None
    pause_until_iso: Optional[str] = None
    last_event_line: int = 0

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    @classmethod
    def load(cls, path: Path) -> "BotState":
        if not path.exists():
            return cls()
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        except Exception:
            return cls()

    def pause_until(self) -> Optional[datetime]:
        if not self.pause_until_iso:
            return None
        try:
            return datetime.fromisoformat(self.pause_until_iso)
        except ValueError:
            return None
