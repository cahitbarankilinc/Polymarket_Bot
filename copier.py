import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from activity_poller import NormalizedEvent
from paper_broker import PaperBroker, TradeRecord
from ws_price_feed import WsPriceFeed


@dataclass
class PendingOrder:
    outcome: str
    side: str
    limit_price: float
    qty: float
    src_price: float
    created_at: float
    expires_at: float
    source_seen_at: float


@dataclass
class CopyStats:
    executed: int = 0
    missed: int = 0
    latency_samples: list[float] = field(default_factory=list)
    slippage_samples: list[float] = field(default_factory=list)


class Copier:
    """Copies source trades into paper orders.

    Inspired by /mnt/data/paper_trading_ByBaran.py (order handling and async task structure).
    """

    def __init__(
        self,
        price_feed: WsPriceFeed,
        broker: PaperBroker,
        share_rate: float,
        ttl_seconds: float = 10.0,
        slippage_bps: float = 0.0,
    ) -> None:
        self.price_feed = price_feed
        self.broker = broker
        self.share_rate = share_rate
        self.ttl_seconds = ttl_seconds
        self.slippage_bps = slippage_bps
        self.pending: list[PendingOrder] = []
        self.stats = CopyStats()
        self._handled_event_ids: set[str] = set()

    @staticmethod
    def _now_ts() -> float:
        return asyncio.get_event_loop().time()

    def _calculate_qty(self, source_qty: Optional[float]) -> float:
        if not source_qty:
            return 1.0
        qty = round(source_qty * self.share_rate, 6)
        return max(1.0, qty)

    def _resolve_outcome(self, event: NormalizedEvent) -> Optional[str]:
        if event.outcome:
            return event.outcome.upper()
        if event.market and "YES" in event.market.upper():
            return "YES"
        if event.market and "NO" in event.market.upper():
            return "NO"
        return None

    async def handle_event(self, event: NormalizedEvent) -> None:
        if event.event_id in self._handled_event_ids:
            return
        if event.type and "trade" not in event.type.lower():
            return
        if not event.side or event.price is None:
            return
        outcome = self._resolve_outcome(event)
        if outcome not in {"YES", "NO"}:
            return
        side = event.side.lower()
        qty = self._calculate_qty(event.size)
        limit_price = event.price
        source_seen_at = self._now_ts()
        pending = PendingOrder(
            outcome=outcome,
            side=side,
            limit_price=limit_price,
            qty=qty,
            src_price=event.price,
            created_at=source_seen_at,
            expires_at=source_seen_at + self.ttl_seconds,
            source_seen_at=source_seen_at,
        )
        self._handled_event_ids.add(event.event_id)
        await self._try_fill(pending)

    async def _try_fill(self, order: PendingOrder) -> None:
        best_bid = self.price_feed.cache.yes.best_bid if order.outcome == "YES" else self.price_feed.cache.no.best_bid
        best_ask = self.price_feed.cache.yes.best_ask if order.outcome == "YES" else self.price_feed.cache.no.best_ask
        can_fill = False
        fill_price = None
        if order.side == "buy" and best_ask is not None and best_ask <= order.limit_price:
            can_fill = True
            fill_price = best_ask
        if order.side == "sell" and best_bid is not None and best_bid >= order.limit_price:
            can_fill = True
            fill_price = best_bid
        if can_fill and fill_price is not None:
            self._execute(order, self._apply_slippage(order, fill_price))
        else:
            self._log_pending(order)
            self.pending.append(order)

    def _execute(self, order: PendingOrder, fill_price: float) -> None:
        fill_time = self._now_ts()
        latency = fill_time - order.source_seen_at
        slippage = fill_price - order.src_price
        self.broker.apply_trade(order.side, order.outcome, fill_price, order.qty)
        record = TradeRecord(
            status="executed",
            side=order.side,
            outcome=order.outcome,
            price=fill_price,
            qty=order.qty,
            src_price=order.src_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            latency=latency,
            slippage=slippage,
        )
        self.broker.log_trade(record)
        self.stats.executed += 1
        self.stats.latency_samples.append(latency)
        self.stats.slippage_samples.append(slippage)

    def _log_pending(self, order: PendingOrder) -> None:
        record = TradeRecord(
            status="pending",
            side=order.side,
            outcome=order.outcome,
            price=order.limit_price,
            qty=order.qty,
            src_price=order.src_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            latency=0.0,
            slippage=0.0,
        )
        self.broker.log_trade(record)

    def _miss(self, order: PendingOrder) -> None:
        record = TradeRecord(
            status="missed",
            side=order.side,
            outcome=order.outcome,
            price=order.limit_price,
            qty=order.qty,
            src_price=order.src_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            latency=self.ttl_seconds,
            slippage=0.0,
        )
        self.broker.log_trade(record)
        self.stats.missed += 1

    async def check_pending(self) -> None:
        now = self._now_ts()
        remaining: list[PendingOrder] = []
        for order in self.pending:
            if now >= order.expires_at:
                self._miss(order)
                continue
            best_bid = self.price_feed.cache.yes.best_bid if order.outcome == "YES" else self.price_feed.cache.no.best_bid
            best_ask = self.price_feed.cache.yes.best_ask if order.outcome == "YES" else self.price_feed.cache.no.best_ask
            if order.side == "buy" and best_ask is not None and best_ask <= order.limit_price:
                self._execute(order, self._apply_slippage(order, best_ask))
            elif order.side == "sell" and best_bid is not None and best_bid >= order.limit_price:
                self._execute(order, self._apply_slippage(order, best_bid))
            else:
                remaining.append(order)
        self.pending = remaining

    def _apply_slippage(self, order: PendingOrder, fill_price: float) -> float:
        if self.slippage_bps <= 0:
            return fill_price
        slippage = fill_price * (self.slippage_bps / 10000)
        if order.side == "buy":
            return fill_price + slippage
        return max(0.0, fill_price - slippage)

    def latency_stats(self) -> tuple[float, float, float]:
        if not self.stats.latency_samples:
            return (0.0, 0.0, 0.0)
        samples = self.stats.latency_samples
        return (min(samples), sum(samples) / len(samples), max(samples))

    def slippage_avg(self) -> float:
        if not self.stats.slippage_samples:
            return 0.0
        return sum(self.stats.slippage_samples) / len(self.stats.slippage_samples)

    def snapshot(self) -> dict:
        min_lat, avg_lat, max_lat = self.latency_stats()
        return {
            "executed": self.stats.executed,
            "missed": self.stats.missed,
            "fill_rate": (self.stats.executed / (self.stats.executed + self.stats.missed))
            if (self.stats.executed + self.stats.missed)
            else 0.0,
            "slippage_avg": self.slippage_avg(),
            "latency": {"min": min_lat, "avg": avg_lat, "max": max_lat},
        }
