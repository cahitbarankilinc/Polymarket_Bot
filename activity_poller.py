import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Iterable, Optional

import aiohttp


ACTIVITY_URL = "https://data-api.polymarket.com/activity"
TRADES_URL = "https://data-api.polymarket.com/trades"


@dataclass
class NormalizedEvent:
    event_id: str
    seen_at_utc: str
    event_time: str
    type: str
    side: Optional[str]
    market: Optional[str]
    outcome: Optional[str]
    price: Optional[float]
    size: Optional[float]
    value_usd: Optional[float]
    tx_hash: Optional[str]
    raw_source: dict


class ActivityPoller:
    """Polls activity endpoints and normalizes events.

    Inspired by /mnt/data/track_polymarket_activity.py (polling cadence, newest-first buffer,
    dedup state persistence, ndjson logging).
    """

    def __init__(
        self,
        address: str,
        poll_interval: float = 1.0,
        max_events_buffer: int = 200,
        output_dir: Path = Path("output"),
    ) -> None:
        self.address = address
        self.poll_interval = poll_interval
        self.max_events_buffer = max_events_buffer
        self.output_dir = output_dir
        self.events: Deque[NormalizedEvent] = deque(maxlen=max_events_buffer)
        self._seen_ids: set[str] = set()
        self.state_path = output_dir / "state.json"
        self.events_path = output_dir / "events.ndjson"
        self.new_events: asyncio.Queue[NormalizedEvent] = asyncio.Queue()
        self._load_state()

    def _load_state(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
            except json.JSONDecodeError:
                data = {}
            seen = data.get("seen_ids", [])
            self._seen_ids = set(seen)

    def _save_state(self) -> None:
        payload = {"seen_ids": list(self._seen_ids)}
        self.state_path.write_text(json.dumps(payload, indent=2))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _event_id(payload: dict) -> str:
        tx_hash = payload.get("tx_hash") or payload.get("txHash")
        if tx_hash:
            return tx_hash
        event_time = payload.get("event_time") or payload.get("timestamp") or "unknown"
        market = payload.get("market") or payload.get("market_title") or "unknown"
        side = payload.get("side") or "unknown"
        size = payload.get("size") or payload.get("shares") or "unknown"
        return f"{event_time}|{market}|{side}|{size}"

    @staticmethod
    def _float_or_none(value: object) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize(self, payload: dict, source: str) -> NormalizedEvent:
        event_time = payload.get("timestamp") or payload.get("event_time") or self._now_iso()
        normalized = NormalizedEvent(
            event_id=self._event_id(payload),
            seen_at_utc=self._now_iso(),
            event_time=event_time,
            type=payload.get("type") or payload.get("event_type") or payload.get("action") or source,
            side=payload.get("side"),
            market=payload.get("market") or payload.get("market_title") or payload.get("market_question"),
            outcome=payload.get("outcome") or payload.get("outcome_name"),
            price=self._float_or_none(payload.get("price")),
            size=self._float_or_none(payload.get("size") or payload.get("shares")),
            value_usd=self._float_or_none(payload.get("value_usd") or payload.get("value")),
            tx_hash=payload.get("tx_hash") or payload.get("txHash"),
            raw_source={"source": source, **payload},
        )
        return normalized

    def _append_event(self, event: NormalizedEvent) -> None:
        self.events.appendleft(event)
        self._seen_ids.add(event.event_id)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.__dict__) + "\n")
        self.new_events.put_nowait(event)
        self._save_state()

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str, params: dict) -> list[dict]:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    async def poll(self) -> Iterable[NormalizedEvent]:
        params = {"user": self.address}
        backoff = 1
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    activity = await self._fetch_json(session, ACTIVITY_URL, params)
                    trades = await self._fetch_json(session, TRADES_URL, params)
                    new_events: list[NormalizedEvent] = []
                    for payload in activity:
                        normalized = self._normalize(payload, "activity")
                        if normalized.event_id not in self._seen_ids:
                            new_events.append(normalized)
                    for payload in trades:
                        normalized = self._normalize(payload, "trades")
                        if normalized.event_id not in self._seen_ids:
                            new_events.append(normalized)
                    for event in sorted(new_events, key=lambda item: item.event_time, reverse=True):
                        self._append_event(event)
                    backoff = 1
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                await asyncio.sleep(self.poll_interval)

    async def replay_from_file(self, path: Path) -> None:
        """Replay mode for offline simulation (inspired by events.ndjson examples)."""
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = json.loads(line)
                normalized = self._normalize(payload, "replay")
                if normalized.event_id not in self._seen_ids:
                    self._append_event(normalized)
                await asyncio.sleep(self.poll_interval)

    async def next_event(self) -> NormalizedEvent:
        return await self.new_events.get()

    def latest_events(self, limit: int = 20) -> list[NormalizedEvent]:
        return list(self.events)[:limit]
