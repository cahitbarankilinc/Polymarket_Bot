from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeeModel:
    fee_bps: float = 0.0
    min_fee: float = 0.0

    def calculate(self, notional: float) -> float:
        if notional <= 0:
            return 0.0
        fee = notional * (self.fee_bps / 10000.0)
        return max(fee, self.min_fee)


def apply_slippage(price: float, slippage_bps: float, side: str) -> float:
    if price <= 0:
        return price
    direction = 1 if side == "BUY" else -1
    return price * (1 + direction * slippage_bps / 10000.0)
