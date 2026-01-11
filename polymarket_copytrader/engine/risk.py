from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from polymarket_copytrader.models import CanonicalTradeEvent


@dataclass
class RiskConfig:
    max_position: Optional[float] = None
    max_notional_usd: Optional[float] = None
    cooldown_ms: int = 0
    allow_partial_sell: bool = True


@dataclass
class RiskState:
    last_trade_ts: Dict[str, datetime] = field(default_factory=dict)


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.state = RiskState()

    def _cooldown_ok(self, market_key: str, now: datetime) -> bool:
        if self.config.cooldown_ms <= 0:
            return True
        last_ts = self.state.last_trade_ts.get(market_key)
        if not last_ts:
            return True
        return now - last_ts >= timedelta(milliseconds=self.config.cooldown_ms)

    def record_trade(self, market_key: str, ts: datetime) -> None:
        self.state.last_trade_ts[market_key] = ts

    def check(self, event: CanonicalTradeEvent, scaled_shares: float, current_qty: float) -> Optional[str]:
        if scaled_shares <= 0:
            return "scaled_shares_zero"

        if not self._cooldown_ok(event.market_id or "unknown", event.ts):
            return "cooldown"

        if self.config.max_position is not None:
            projected = current_qty
            if event.side == "BUY":
                projected += scaled_shares
            else:
                projected -= scaled_shares
            if abs(projected) > self.config.max_position:
                return "max_position"

        if self.config.max_notional_usd is not None:
            notional = scaled_shares * event.price
            if notional > self.config.max_notional_usd:
                return "max_notional"

        if event.side == "SELL" and current_qty <= 0 and not self.config.allow_partial_sell:
            return "insufficient_position"

        return None
