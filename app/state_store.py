from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from .config import DEFAULT_OUTPUT_DIR, AppConfig

STATE_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "state.json")
EVENTS_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "events.ndjson")
ORDERS_PATH = os.path.join(DEFAULT_OUTPUT_DIR, "paper_trades.ndjson")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MarketInfo:
    market_id: Optional[str] = None
    market_name: Optional[str] = None
    end_time: Optional[str] = None
    yes_asset_id: Optional[str] = None
    no_asset_id: Optional[str] = None
    last_refresh_utc: Optional[str] = None


@dataclass
class PriceSnapshot:
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid: Optional[float] = None
    last_update_utc: Optional[str] = None


@dataclass
class PaperStats:
    total_trades_source: int = 0
    total_orders_created: int = 0
    total_trades_executed: int = 0
    total_trades_missed: int = 0
    total_shares_bought_yes: float = 0.0
    total_shares_sold_yes: float = 0.0
    total_shares_bought_no: float = 0.0
    total_shares_sold_no: float = 0.0
    slippage_samples: List[float] = field(default_factory=list)
    latency_samples: List[float] = field(default_factory=list)


@dataclass
class Position:
    qty: float = 0.0
    avg_price: float = 0.0


@dataclass
class PaperState:
    positions: Dict[str, Position] = field(default_factory=lambda: {"YES": Position(), "NO": Position()})
    cash_spent_usd: float = 0.0
    cash_received_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    orders: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    stats: PaperStats = field(default_factory=PaperStats)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "positions": {
                side: {"qty": pos.qty, "avg_price": pos.avg_price}
                for side, pos in self.positions.items()
            },
            "cash_spent_usd": self.cash_spent_usd,
            "cash_received_usd": self.cash_received_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "orders": self.orders,
            "stats": {
                **self.stats.__dict__,
                "latency_seconds_min": min(self.stats.latency_samples) if self.stats.latency_samples else None,
                "latency_seconds_avg": (
                    sum(self.stats.latency_samples) / len(self.stats.latency_samples)
                    if self.stats.latency_samples
                    else None
                ),
                "latency_seconds_max": max(self.stats.latency_samples) if self.stats.latency_samples else None,
                "slippage_vs_source_avg": (
                    sum(self.stats.slippage_samples) / len(self.stats.slippage_samples)
                    if self.stats.slippage_samples
                    else None
                ),
            },
        }


class StateStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.market = MarketInfo()
        self.price_cache: Dict[str, PriceSnapshot] = {"YES": PriceSnapshot(), "NO": PriceSnapshot()}
        self.events: Deque[Dict[str, Any]] = deque(maxlen=config.max_events_buffer)
        self.orders: Deque[Dict[str, Any]] = deque(maxlen=500)
        self.paper_state = PaperState()
        self.seen_ids: set[str] = set()
        self.seen_queue: Deque[str] = deque(maxlen=config.max_events_buffer)
        self.lock = asyncio.Lock()
        self.event_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.load_state()

    def load_state(self) -> None:
        if not os.path.exists(STATE_PATH):
            return
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.seen_ids = set(payload.get("seen_ids", []))
            self.seen_queue = deque(payload.get("seen_queue", []), maxlen=self.config.max_events_buffer)
        except Exception:
            self.seen_ids = set()
            self.seen_queue = deque(maxlen=self.config.max_events_buffer)

    def save_state(self) -> None:
        payload = {
            "seen_ids": sorted(self.seen_ids),
            "seen_queue": list(self.seen_queue),
            "last_check": utc_now_iso(),
        }
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    async def add_event(self, event: Dict[str, Any]) -> None:
        async with self.lock:
            self.events.appendleft(event)
        await self.event_queue.put(event)
        self._append_ndjson(EVENTS_PATH, event)

    async def add_order_event(self, order_event: Dict[str, Any]) -> None:
        async with self.lock:
            self.orders.appendleft(order_event)
        self._append_ndjson(ORDERS_PATH, order_event)

    def update_config(self, config: AppConfig) -> None:
        self.config = config
        self.events = deque(self.events, maxlen=config.max_events_buffer)
        self.seen_queue = deque(self.seen_queue, maxlen=config.max_events_buffer)

    async def snapshot(self) -> Dict[str, Any]:
        async with self.lock:
            mark_prices = {
                side: (snap.mid if snap.mid is not None else snap.best_bid)
                for side, snap in self.price_cache.items()
            }
            unrealized = 0.0
            for side, pos in self.paper_state.positions.items():
                mark = mark_prices.get(side)
                if mark is None or pos.qty == 0:
                    continue
                unrealized += (mark - pos.avg_price) * pos.qty
            paper_snapshot = self.paper_state.snapshot()
            paper_snapshot["unrealized_pnl_usd"] = unrealized
            paper_snapshot["total_pnl_usd"] = unrealized + self.paper_state.realized_pnl_usd
            return {
                "config": self.config.to_dict(),
                "market": self.market.__dict__,
                "price_cache": {k: v.__dict__ for k, v in self.price_cache.items()},
                "paper": paper_snapshot,
            }

    async def list_events(self, limit: int) -> List[Dict[str, Any]]:
        async with self.lock:
            return list(self.events)[:limit]

    async def list_orders(self, limit: int) -> List[Dict[str, Any]]:
        async with self.lock:
            return list(self.orders)[:limit]

    @staticmethod
    def _append_ndjson(path: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
