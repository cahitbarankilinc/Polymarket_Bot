from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from uuid import uuid4

from .paper_broker import PaperBroker
from .state_store import StateStore

logger = logging.getLogger(__name__)

# Inspired by paper_trading_ByBaran.py: async orchestration of WS + paper order fills.

@dataclass
class PendingOrder:
    order_id: str
    src_event_id: str
    outcome: str
    side: str
    qty: float
    src_price: float
    limit_price: float
    created_at: str
    expires_at: str
    source_seen_at: str


def _parse_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_outcome(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.upper()
    if value in ("YES", "NO"):
        return value
    return None


def _normalize_side(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.upper()
    if value in ("BUY", "SELL"):
        return value
    return None


class CopyEngine:
    def __init__(self, state: StateStore):
        self.state = state
        self.pending: Dict[str, PendingOrder] = {}
        self.broker = PaperBroker(state.paper_state)

    def _limit_price(self, src_price: float) -> float:
        config = self.state.config
        if not config.slippage_enabled or config.slippage_bps == 0:
            return src_price
        adjustment = src_price * (config.slippage_bps / 10000)
        return max(0.0, min(1.0, src_price + adjustment))

    def _can_fill(self, outcome: str, side: str, limit: float) -> Optional[float]:
        snapshot = self.state.price_cache.get(outcome)
        if not snapshot:
            return None
        if side == "BUY" and snapshot.best_ask is not None and snapshot.best_ask <= limit:
            return snapshot.best_ask
        if side == "SELL" and snapshot.best_bid is not None and snapshot.best_bid >= limit:
            return snapshot.best_bid
        return None

    async def handle_source_event(self, event: Dict[str, object]) -> None:
        side = _normalize_side(event.get("side"))
        outcome = _normalize_outcome(event.get("outcome"))
        price = _parse_float(event.get("price"))
        size = _parse_float(event.get("size"))
        if not side or not outcome or price is None or size is None:
            return

        self.broker.record_source_trade()
        config = self.state.config
        qty = max(1.0, round(size * config.individual_share_rate, 6))
        limit_price = self._limit_price(price)
        order_id = uuid4().hex
        created_at = _now_iso()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=config.order_ttl_seconds)
        pending = PendingOrder(
            order_id=order_id,
            src_event_id=event.get("event_id", ""),
            outcome=outcome,
            side=side,
            qty=qty,
            src_price=price,
            limit_price=limit_price,
            created_at=created_at,
            expires_at=expires_at.isoformat(),
            source_seen_at=event.get("seen_at_utc", created_at),
        )
        self.pending[order_id] = pending
        order_payload = {
            "order_id": order_id,
            "src_event_id": pending.src_event_id,
            "outcome": outcome,
            "side": side,
            "my_qty": qty,
            "src_price": price,
            "limit": limit_price,
            "created_at": created_at,
            "status": "order_created",
        }
        self.broker.record_order_created(order_id, order_payload)
        await self.state.add_order_event(order_payload)

        await self._try_fill(order_id, pending)

    async def _try_fill(self, order_id: str, pending: PendingOrder) -> None:
        exec_price = self._can_fill(pending.outcome, pending.side, pending.limit_price)
        if exec_price is None:
            return

        result = self.broker.execute_order(
            order_id,
            pending.outcome,
            pending.side,
            pending.qty,
            exec_price,
        )
        if not result.valid:
            await self._mark_invalid(order_id, pending, result.reason)
            return

        filled_at = _now_iso()
        latency = _latency_seconds(pending.source_seen_at, filled_at)
        if latency is not None:
            self.broker.append_latency(latency)
        self.broker.append_slippage(exec_price - pending.src_price)
        order_payload = {
            "order_id": order_id,
            "src_event_id": pending.src_event_id,
            "outcome": pending.outcome,
            "side": pending.side,
            "my_qty": pending.qty,
            "src_price": pending.src_price,
            "limit": pending.limit_price,
            "exec_price": exec_price,
            "created_at": pending.created_at,
            "filled_at": filled_at,
            "status": "order_executed",
        }
        await self.state.add_order_event(order_payload)
        self.pending.pop(order_id, None)

    async def _mark_invalid(self, order_id: str, pending: PendingOrder, reason: str) -> None:
        payload = {
            "order_id": order_id,
            "src_event_id": pending.src_event_id,
            "outcome": pending.outcome,
            "side": pending.side,
            "my_qty": pending.qty,
            "src_price": pending.src_price,
            "limit": pending.limit_price,
            "created_at": pending.created_at,
            "status": "order_invalid",
            "reason": reason,
        }
        await self.state.add_order_event(payload)
        self.pending.pop(order_id, None)

    async def _mark_missed(self, order_id: str, pending: PendingOrder) -> None:
        self.broker.mark_missed()
        payload = {
            "order_id": order_id,
            "src_event_id": pending.src_event_id,
            "outcome": pending.outcome,
            "side": pending.side,
            "my_qty": pending.qty,
            "src_price": pending.src_price,
            "limit": pending.limit_price,
            "created_at": pending.created_at,
            "status": "order_missed",
            "reason": "ttl_expired",
        }
        await self.state.add_order_event(payload)
        self.pending.pop(order_id, None)

    async def tick_pending(self) -> None:
        now = datetime.now(timezone.utc)
        for order_id, pending in list(self.pending.items()):
            if datetime.fromisoformat(pending.expires_at) <= now:
                await self._mark_missed(order_id, pending)
                continue
            await self._try_fill(order_id, pending)


def _latency_seconds(start_iso: str, end_iso: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        return (end - start).total_seconds()
    except Exception:
        return None


async def run_copy_engine(state: StateStore, stop_event: asyncio.Event) -> None:
    engine = CopyEngine(state)

    async def consume_events() -> None:
        while not stop_event.is_set():
            event = await state.event_queue.get()
            await engine.handle_source_event(event)

    async def process_pending() -> None:
        while not stop_event.is_set():
            await engine.tick_pending()
            await asyncio.sleep(0.3)

    await asyncio.gather(consume_events(), process_pending())
