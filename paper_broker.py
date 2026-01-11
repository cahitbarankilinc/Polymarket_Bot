import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class Position:
    qty: float = 0.0
    avg_price: float = 0.0


@dataclass
class PnLState:
    realized: float = 0.0
    unrealized: float = 0.0
    total_spent: float = 0.0
    total_received: float = 0.0
    total_shares_bought: Dict[str, float] = field(default_factory=lambda: {"YES": 0.0, "NO": 0.0})
    total_shares_sold: Dict[str, float] = field(default_factory=lambda: {"YES": 0.0, "NO": 0.0})


@dataclass
class TradeRecord:
    status: str
    side: str
    outcome: str
    price: float
    qty: float
    src_price: float
    timestamp: str
    latency: float
    slippage: float


class PaperBroker:
    """Tracks positions and PnL for paper trading.

    Inspired by /mnt/data/paper_trading_ByBaran.py (position accounting and PnL updates).
    """

    def __init__(self, output_dir: Path = Path("output")) -> None:
        self.positions: Dict[str, Position] = {"YES": Position(), "NO": Position()}
        self.pnl = PnLState()
        self.output_path = output_dir / "paper_trades.ndjson"
        self.trades: list[TradeRecord] = []

    def apply_trade(self, side: str, outcome: str, price: float, qty: float) -> None:
        position = self.positions[outcome]
        if side == "buy":
            new_qty = position.qty + qty
            if new_qty > 0:
                position.avg_price = (position.avg_price * position.qty + price * qty) / new_qty
            position.qty = new_qty
            self.pnl.total_spent += price * qty
            self.pnl.total_shares_bought[outcome] += qty
        else:
            realized = (price - position.avg_price) * qty
            position.qty = max(0.0, position.qty - qty)
            self.pnl.realized += realized
            self.pnl.total_received += price * qty
            self.pnl.total_shares_sold[outcome] += qty

    def update_unrealized(self, yes_price: Optional[float], no_price: Optional[float]) -> None:
        unrealized = 0.0
        if yes_price is not None:
            unrealized += (yes_price - self.positions["YES"].avg_price) * self.positions["YES"].qty
        if no_price is not None:
            unrealized += (no_price - self.positions["NO"].avg_price) * self.positions["NO"].qty
        self.pnl.unrealized = unrealized

    def log_trade(self, record: TradeRecord) -> None:
        self.trades.append(record)
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.__dict__) + "\n")

    def snapshot(self) -> dict:
        return {
            "positions": {
                "YES": {"qty": self.positions["YES"].qty, "avg_price": self.positions["YES"].avg_price},
                "NO": {"qty": self.positions["NO"].qty, "avg_price": self.positions["NO"].avg_price},
            },
            "pnl": {
                "realized": self.pnl.realized,
                "unrealized": self.pnl.unrealized,
                "total_spent": self.pnl.total_spent,
                "total_received": self.pnl.total_received,
                "total_shares_bought": self.pnl.total_shares_bought,
                "total_shares_sold": self.pnl.total_shares_sold,
            },
        }
