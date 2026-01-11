from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

from polymarket_copytrader.engine.pricing import FeeModel
from polymarket_copytrader.models import Metrics, PaperTrade, Position


@dataclass
class MarketPosition:
    yes: Position = field(default_factory=Position)
    no: Position = field(default_factory=Position)


class PaperTrader:
    def __init__(self, fee_model: FeeModel) -> None:
        self.positions: Dict[str, MarketPosition] = {}
        self.metrics = Metrics()
        self.fee_model = fee_model
        self.last_prices: Dict[Tuple[str, Optional[str]], float] = {}

    def _get_market(self, market_id: Optional[str]) -> MarketPosition:
        key = market_id or "unknown"
        if key not in self.positions:
            self.positions[key] = MarketPosition()
        return self.positions[key]

    def update_mark_price(self, market_id: Optional[str], outcome: Optional[str], price: float) -> None:
        if market_id and price:
            self.last_prices[(market_id, outcome)] = price

    def mark_price(self, market_id: Optional[str], outcome: Optional[str]) -> float:
        return self.last_prices.get((market_id or "unknown", outcome), 0.0)

    def execute(
        self,
        trade_id: str,
        ts: datetime,
        market_id: Optional[str],
        market_slug: Optional[str],
        outcome: Optional[str],
        side: str,
        shares: float,
        price: float,
        user_event_id: str,
        allow_partial_sell: bool = True,
    ) -> PaperTrade:
        market = self._get_market(market_id)
        position = market.yes if (outcome or "").upper() == "YES" else market.no

        realized = 0.0
        executed_shares = shares
        status = "filled"
        if side == "SELL":
            if position.qty <= 0:
                executed_shares = 0.0
                status = "ignored"
            elif shares > position.qty:
                if allow_partial_sell:
                    executed_shares = position.qty
                    status = "partial"
                else:
                    executed_shares = 0.0
                    status = "ignored"

        notional = executed_shares * price
        fee = self.fee_model.calculate(notional)

        if executed_shares > 0:
            if side == "BUY":
                position.apply_buy(executed_shares, price)
                self.metrics.total_spent += notional
            else:
                avg_cost = position.avg_cost
                sold_qty = position.apply_sell(executed_shares)
                realized = (price - avg_cost) * sold_qty
                self.metrics.total_received += notional
                self.metrics.realized_pnl += realized

            self.metrics.total_fees += fee
            self.metrics.total_volume += notional

        trade = PaperTrade(
            trade_id=trade_id,
            ts=ts,
            market_id=market_id,
            market_slug=market_slug,
            outcome=outcome,
            side=side,
            shares=executed_shares,
            price=price,
            notional=notional,
            fee=fee,
            status=status,
            user_event_id=user_event_id,
        )
        return trade

    def recompute_unrealized(self) -> float:
        total = 0.0
        for market_id, market in self.positions.items():
            for outcome, position in (("YES", market.yes), ("NO", market.no)):
                if position.qty == 0:
                    continue
                mark = self.mark_price(market_id, outcome)
                total += (mark - position.avg_cost) * position.qty
        self.metrics.unrealized_pnl = total
        return total
