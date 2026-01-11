from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CanonicalTradeEvent:
    event_id: str
    ts: datetime
    wallet: str
    market_id: Optional[str]
    market_slug: Optional[str]
    question: Optional[str]
    asset_id: Optional[str]
    side: str
    outcome: Optional[str]
    shares: float
    price: float
    notional: Optional[float]
    source: str
    raw: dict = field(default_factory=dict)


@dataclass
class PaperTrade:
    trade_id: str
    ts: datetime
    market_id: Optional[str]
    market_slug: Optional[str]
    outcome: Optional[str]
    side: str
    shares: float
    price: float
    notional: float
    fee: float
    status: str
    user_event_id: str


@dataclass
class Position:
    qty: float = 0.0
    avg_cost: float = 0.0

    def apply_buy(self, shares: float, price: float) -> None:
        if shares <= 0:
            return
        total_cost = self.avg_cost * self.qty + price * shares
        self.qty += shares
        self.avg_cost = total_cost / self.qty if self.qty else 0.0

    def apply_sell(self, shares: float) -> float:
        if shares <= 0:
            return 0.0
        sell_qty = min(self.qty, shares)
        self.qty -= sell_qty
        if self.qty == 0:
            self.avg_cost = 0.0
        return sell_qty


@dataclass
class Metrics:
    total_spent: float = 0.0
    total_received: float = 0.0
    total_fees: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_volume: float = 0.0


@dataclass
class CopyResult:
    accepted: bool
    reason: Optional[str] = None
    paper_trade: Optional[PaperTrade] = None
