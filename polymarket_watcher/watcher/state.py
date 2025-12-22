from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set


@dataclass
class BotState:
    logged_timestamps: Set[int] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "BotState":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            if "logged_timestamps" in data:
                logged = set(int(item) for item in data.get("logged_timestamps", []))
            elif "seen_timestamps" in data:
                logged = set(int(item) for item in data.get("seen_timestamps", []))
            else:
                logged = set()
                for event_key in data.get("seen_events", []):
                    try:
                        ts = int(str(event_key).split("-")[-1])
                        logged.add(ts)
                    except (ValueError, TypeError):
                        continue
            return cls(logged_timestamps=logged)
        except Exception:  # pylint: disable=broad-exception-caught
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"logged_timestamps": sorted(self.logged_timestamps)}
        path.write_text(json.dumps(payload, indent=2))

    def has_logged(self, timestamp: int) -> bool:
        return timestamp in self.logged_timestamps

    def mark_logged(self, timestamp: int, path: Path) -> None:
        self.logged_timestamps.add(timestamp)
        self.save(path)
