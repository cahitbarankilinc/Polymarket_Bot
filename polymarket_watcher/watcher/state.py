from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set


@dataclass
class BotState:
    seen_events: Set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "BotState":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            seen_events = set(data.get("seen_events", []))
            return cls(seen_events=seen_events)
        except Exception:  # pylint: disable=broad-exception-caught
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seen_events": sorted(self.seen_events)}
        path.write_text(json.dumps(payload, indent=2))

    def has_seen(self, event_key: str) -> bool:
        return event_key in self.seen_events

    def mark_seen(self, event_key: str, path: Path) -> None:
        self.seen_events.add(event_key)
        self.save(path)
