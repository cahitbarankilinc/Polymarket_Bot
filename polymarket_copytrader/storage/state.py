from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Set


@dataclass
class StateStore:
    path: Path
    max_size: int = 10000
    event_ids: Deque[str] = field(default_factory=deque)
    event_id_set: Set[str] = field(default_factory=set)

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        ids = data.get("event_ids", [])
        self.event_ids = deque(ids, maxlen=self.max_size)
        self.event_id_set = set(self.event_ids)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"event_ids": list(self.event_ids)}
        self.path.write_text(json.dumps(data, indent=2))

    def seen(self, event_id: str) -> bool:
        return event_id in self.event_id_set

    def add(self, event_id: str) -> None:
        if event_id in self.event_id_set:
            return
        if len(self.event_ids) >= self.max_size:
            oldest = self.event_ids.popleft()
            self.event_id_set.discard(oldest)
        self.event_ids.append(event_id)
        self.event_id_set.add(event_id)
