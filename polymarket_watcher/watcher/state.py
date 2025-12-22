from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set


@dataclass
class BotState:
    seen_timestamps: Set[int] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "BotState":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            if "seen_timestamps" in data:
                seen = set(int(item) for item in data.get("seen_timestamps", []))
            else:
                seen = set()
                for event_key in data.get("seen_events", []):
                    try:
                        ts = int(str(event_key).split("-")[-1])
                        seen.add(ts)
                    except (ValueError, TypeError):
                        continue
            return cls(seen_timestamps=seen)
        except Exception:  # pylint: disable=broad-exception-caught
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seen_timestamps": sorted(self.seen_timestamps)}
        path.write_text(json.dumps(payload, indent=2))

    def has_seen(self, timestamp: int) -> bool:
        return timestamp in self.seen_timestamps

    def mark_seen(self, timestamp: int, path: Path) -> None:
        self.seen_timestamps.add(timestamp)
        self.save(path)
