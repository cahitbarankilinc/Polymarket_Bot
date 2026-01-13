from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .state_store import PaperState, Position


@dataclass
class ExecutionResult:
    valid: bool
    reason: str = ""


class PaperBroker:
    def __init__(self, state: PaperState):
        self.state = state

    def _position_for(self, outcome: str) -> Position:
        return self.state.positions.setdefault(outcome, Position())

    def record_source_trade(self) -> None:
        self.state.stats.total_trades_source += 1

    def record_order_created(self, order_id: str, order: Dict[str, float]) -> None:
        self.state.stats.total_orders_created += 1
        self.state.orders[order_id] = order

    def execute_order(
        self,
        order_id: str,
        outcome: str,
        side: str,
        qty: float,
        price: float,
    ) -> ExecutionResult:
        pos = self._position_for(outcome)
        if side == "BUY":
            new_qty = pos.qty + qty
            if new_qty <= 0:
                return ExecutionResult(False, "invalid_qty")
            pos.avg_price = ((pos.avg_price * pos.qty) + (price * qty)) / new_qty
            pos.qty = new_qty
            self.state.cash_spent_usd += price * qty
            self.state.stats.total_trades_executed += 1
            if outcome == "YES":
                self.state.stats.total_shares_bought_yes += qty
            else:
                self.state.stats.total_shares_bought_no += qty
            return ExecutionResult(True)

        if side == "SELL":
            if pos.qty <= 0:
                return ExecutionResult(False, "no_position")
            sell_qty = min(qty, pos.qty)
            if sell_qty <= 0:
                return ExecutionResult(False, "invalid_qty")
            realized = (price - pos.avg_price) * sell_qty
            pos.qty -= sell_qty
            self.state.realized_pnl_usd += realized
            self.state.cash_received_usd += price * sell_qty
            self.state.stats.total_trades_executed += 1
            if outcome == "YES":
                self.state.stats.total_shares_sold_yes += sell_qty
            else:
                self.state.stats.total_shares_sold_no += sell_qty
            return ExecutionResult(True)

        return ExecutionResult(False, "unknown_side")

    def mark_missed(self) -> None:
        self.state.stats.total_trades_missed += 1

    def append_latency(self, latency: float) -> None:
        self.state.stats.latency_samples.append(latency)

    def append_slippage(self, slippage: float) -> None:
        self.state.stats.slippage_samples.append(slippage)

    def unrealized_pnl(self, mark_prices: Dict[str, float]) -> float:
        pnl = 0.0
        for side, pos in self.state.positions.items():
            if pos.qty == 0:
                continue
            mark = mark_prices.get(side)
            if mark is None:
                continue
            pnl += (mark - pos.avg_price) * pos.qty
        return pnl
