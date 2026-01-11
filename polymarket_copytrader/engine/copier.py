from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Callable, Optional

from polymarket_copytrader.engine.pricing import apply_slippage
from polymarket_copytrader.engine.risk import RiskManager
from polymarket_copytrader.models import CanonicalTradeEvent, CopyResult
from polymarket_copytrader.engine.paper import PaperTrader


class CopyEngine:
    def __init__(
        self,
        multiplier: float,
        slippage_bps: float,
        risk_manager: RiskManager,
        paper_trader: PaperTrader,
        on_trade: Optional[Callable[[CopyResult], None]] = None,
    ) -> None:
        self.multiplier = multiplier
        self.slippage_bps = slippage_bps
        self.risk_manager = risk_manager
        self.paper_trader = paper_trader
        self.on_trade = on_trade

    def _trade_id(self, event_id: str, ts: datetime) -> str:
        raw = f"{event_id}:{ts.isoformat()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def process(self, event: CanonicalTradeEvent) -> CopyResult:
        scaled_shares = round(event.shares * self.multiplier, 6)
        market_key = event.market_id or "unknown"
        positions = self.paper_trader.positions.get(market_key)
        if positions:
            position = positions.yes if (event.outcome or "").upper() == "YES" else positions.no
            current_qty = position.qty
        else:
            current_qty = 0.0

        reason = self.risk_manager.check(event, scaled_shares, current_qty)
        if reason:
            result = CopyResult(accepted=False, reason=reason)
            if self.on_trade:
                self.on_trade(result)
            return result

        price = apply_slippage(event.price, self.slippage_bps, event.side)
        trade = self.paper_trader.execute(
            trade_id=self._trade_id(event.event_id, event.ts),
            ts=event.ts,
            market_id=event.market_id,
            market_slug=event.market_slug,
            outcome=event.outcome,
            side=event.side,
            shares=scaled_shares,
            price=price,
            user_event_id=event.event_id,
            allow_partial_sell=self.risk_manager.config.allow_partial_sell,
        )
        self.paper_trader.update_mark_price(event.market_id, event.outcome, price)
        self.paper_trader.recompute_unrealized()
        self.risk_manager.record_trade(event.market_id or "unknown", event.ts)

        result = CopyResult(accepted=True, paper_trade=trade)
        if self.on_trade:
            self.on_trade(result)
        return result
