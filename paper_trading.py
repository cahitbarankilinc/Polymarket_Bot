import argparse
import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import websockets

from discovery import find_active_window

# ---------------------------------------------------------------------------
# STRATEGY SETTINGS (change defaults here or via CLI)
# - Pricing: set your fair value for YES; NO is derived as 1 - fair_yes.
# - Entry/Exit edges: how far the live price must be from fair to buy/sell.
# - Sizing/Exposure: how big each order is and the max size per side.
# - Pace: cooldown between trades per side and how often to log status.
# - Fees: fee_bps deducts per-trade costs from PnL.
# - Side filter: trade both tokens or only YES/NO.
# ---------------------------------------------------------------------------

# Toggle this to True to run with the preset config below (no CLI flags needed).
USE_PRESET = True

# Strategy + run settings you can edit directly in-file.
PRESET_CONFIG = {
    "fair_yes": 0.55,        # Your fair value for YES (0-1); NO is 1 - fair_yes
    "entry_edge": 0.015,     # Buy when ask <= fair - entry_edge
    "exit_edge": 0.02,       # Sell when bid >= fair + exit_edge (defaults to entry_edge if None)
    "order_size": 5.0,       # Size per trade (shares/contracts)
    "max_position": 50.0,    # Max open size per side
    "cooldown": 5.0,         # Seconds between trades per side
    "status_interval": 10.0, # How often to print status/PnL
    "run_seconds": None,     # Stop after N seconds; None to run indefinitely
    "fee_bps": 35.0,         # Fee in basis points (deducted from PnL)
    "side_mode": "both",     # "both", "yes-only", or "no-only"
}

# Optional manual market override; if ids are None the script will auto-discover.
PRESET_MARKET = {
    "yes_id": None,
    "no_id": None,
    "title": "Manual Market",
    "end_time": None,
}

# WebSocket endpoint for Polymarket level1 updates
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class TraderConfig:
    fair_yes: float
    entry_edge: float
    exit_edge: float
    order_size: float
    max_position: float
    cooldown: float
    status_interval: float
    run_seconds: Optional[float]
    fee_bps: float
    side_mode: str


class PaperTrader:
    """Lightweight paper trading loop that reacts to live best bid/ask ticks."""

    def __init__(self, market: Dict, config: TraderConfig):
        self.market = market
        self.ids = {"YES": market["yes_id"], "NO": market["no_id"]}
        self.config = config
        self.tradeable_sides = (
            {"YES", "NO"}
            if config.side_mode == "both"
            else {"YES"} if config.side_mode == "yes-only" else {"NO"}
        )

        self.books = {
            "YES": {"bid": None, "ask": None},
            "NO": {"bid": None, "ask": None},
        }
        self.positions = {
            "YES": {"qty": 0.0, "avg": 0.0},
            "NO": {"qty": 0.0, "avg": 0.0},
        }
        self.realized = 0.0
        self.last_trade_time = {"YES": 0.0, "NO": 0.0}
        self.start_time = datetime.now(timezone.utc)

        print("\n--- Paper Trader ---")
        print(f"Market: {market.get('title', 'Custom')}")
        print(f"YES: {self.ids['YES']} | NO: {self.ids['NO']}")
        if market.get("end_time"):
            print(f"Ends:  {market['end_time']}")
        print(
            f"fair_yes={config.fair_yes:.3f} entry={config.entry_edge:.3f} "
            f"exit={config.exit_edge:.3f} size={config.order_size} "
            f"max_pos={config.max_position} fee_bps={config.fee_bps} sides={config.side_mode}"
        )
        print("-" * 60)

    # ---------- Helpers ----------
    def fair_price(self, side: str) -> float:
        return self.config.fair_yes if side == "YES" else 1 - self.config.fair_yes

    def mid_price(self, side: str) -> Optional[float]:
        book = self.books[side]
        bid, ask = book["bid"], book["ask"]
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return bid or ask

    def unrealized_pnl(self) -> float:
        pnl = 0.0
        for side, pos in self.positions.items():
            mid = self.mid_price(side)
            if mid is not None and pos["qty"] != 0:
                pnl += (mid - pos["avg"]) * pos["qty"]
        return pnl

    def total_pnl(self) -> float:
        return self.realized + self.unrealized_pnl()

    # ---------- Book + Trade Logic ----------
    def update_book(self, asset_id: str, bid: Optional[float], ask: Optional[float]):
        side = None
        for k, v in self.ids.items():
            if asset_id == v:
                side = k
                break
        if side is None:
            return
        if side not in self.tradeable_sides:
            return

        if bid is not None:
            self.books[side]["bid"] = bid
        if ask is not None:
            self.books[side]["ask"] = ask

        self.maybe_trade(side)

    def maybe_trade(self, side: str):
        now = asyncio.get_running_loop().time()
        if now - self.last_trade_time[side] < self.config.cooldown:
            return

        book = self.books[side]
        bid, ask = book["bid"], book["ask"]
        if bid is None or ask is None:
            return

        fair = self.fair_price(side)
        size = self.config.order_size
        max_pos = self.config.max_position
        pos = self.positions[side]["qty"]

        # Long bias: buy when we see value, sell when it richens
        if pos < max_pos and ask <= fair - self.config.entry_edge:
            buyable = max_pos - pos
            if buyable > 0:
                trade_size = min(size, buyable)
                self.execute_trade(side, "BUY", ask, trade_size)
                self.last_trade_time[side] = now
        elif pos > 0 and bid >= fair + self.config.exit_edge:
            sell_size = min(pos, size)
            self.execute_trade(side, "SELL", bid, sell_size)
            self.last_trade_time[side] = now

    def execute_trade(self, side: str, direction: str, price: float, size: float):
        fee = price * size * (self.config.fee_bps / 10_000)
        pos = self.positions[side]

        if direction == "BUY":
            new_qty = pos["qty"] + size
            pos["avg"] = (pos["avg"] * pos["qty"] + price * size) / new_qty
            pos["qty"] = new_qty
            self.realized -= fee
        else:  # SELL
            realized_leg = (price - pos["avg"]) * size
            pos["qty"] -= size
            if pos["qty"] == 0:
                pos["avg"] = 0.0
            self.realized += realized_leg - fee

        self.log_trade(side, direction, price, size, fee)

    # ---------- Logging ----------
    def log_trade(self, side: str, direction: str, price: float, size: float, fee: float):
        mid_val = self.mid_price(side)
        mid = f"{mid_val:.4f}" if mid_val is not None else "--"
        pos = self.positions[side]
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] {direction:<4} {side} "
            f"@ {price:.4f} x {size:.2f} | fee {fee:.4f} | "
            f"pos {pos['qty']:.2f} @ {pos['avg']:.4f} | mid {mid} | "
            f"PNL r{self.realized:.4f} / u{self.unrealized_pnl():.4f} / t{self.total_pnl():.4f}"
        )

    def print_status(self):
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        yes_book = self.books["YES"]
        no_book = self.books["NO"]

        def fmt(val: Optional[float]) -> str:
            return f"{val:.4f}" if val is not None else "--"

        print(
            f"[t+{elapsed:.0f}s] "
            f"YES b{fmt(yes_book['bid'])} a{fmt(yes_book['ask'])} | "
            f"NO b{fmt(no_book['bid'])} a{fmt(no_book['ask'])} | "
            f"pos YES {self.positions['YES']['qty']:.2f} NO {self.positions['NO']['qty']:.2f} | "
            f"PNL r{self.realized:.4f} u{self.unrealized_pnl():.4f} t{self.total_pnl():.4f}"
        )

    # ---------- Run Loop ----------
    async def run(self):
        status_task = asyncio.create_task(self._status_loop())
        try:
            async with websockets.connect(WS_URL) as ws:
                sub_msg = {
                    "assets_ids": [self.ids["YES"], self.ids["NO"]],
                    "type": "level1",
                }
                await ws.send(json.dumps(sub_msg))

                while True:
                    if self.config.run_seconds:
                        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
                        if elapsed >= self.config.run_seconds:
                            print("\n⏱️ Run timer reached, shutting down.")
                            break

                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=10)
                        data = json.loads(msg)
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            self.process_item(item)
                    except asyncio.TimeoutError:
                        await ws.ping()
                    except websockets.ConnectionClosed:
                        print("WebSocket closed, exiting.")
                        break
        finally:
            status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await status_task

    async def _status_loop(self):
        while True:
            await asyncio.sleep(self.config.status_interval)
            self.print_status()

    def process_item(self, item: Dict):
        event_type = item.get("event_type")
        if event_type == "level1":
            self.update_book(
                item.get("asset_id"),
                bid=float(item.get("best_bid") or 0) or None,
                ask=float(item.get("best_ask") or 0) or None,
            )
        elif event_type == "price_change":
            for c in item.get("price_changes", []):
                self.update_book(
                    c.get("asset_id"),
                    bid=float(c.get("best_bid") or 0) or None,
                    ask=float(c.get("best_ask") or 0) or None,
                )
        elif event_type == "book":
            asks = item.get("asks", [])
            bids = item.get("bids", [])
            ask_price = float(asks[0]["price"]) if asks else None
            bid_price = float(bids[0]["price"]) if bids else None
            self.update_book(item.get("asset_id"), bid_price, ask_price)


def config_from_preset() -> TraderConfig:
    exit_edge = PRESET_CONFIG.get("exit_edge")
    entry_edge = PRESET_CONFIG["entry_edge"]
    if exit_edge is None:
        exit_edge = entry_edge

    side_mode = PRESET_CONFIG.get("side_mode", "both")
    if side_mode not in {"both", "yes-only", "no-only"}:
        side_mode = "both"

    return TraderConfig(
        fair_yes=PRESET_CONFIG["fair_yes"],
        entry_edge=entry_edge,
        exit_edge=exit_edge,
        order_size=PRESET_CONFIG["order_size"],
        max_position=PRESET_CONFIG["max_position"],
        cooldown=PRESET_CONFIG["cooldown"],
        status_interval=PRESET_CONFIG["status_interval"],
        run_seconds=PRESET_CONFIG["run_seconds"],
        fee_bps=PRESET_CONFIG["fee_bps"],
        side_mode=side_mode,
    )


async def resolve_market(args: argparse.Namespace) -> Optional[Dict]:
    if args.yes_id and args.no_id:
        return {
            "title": args.title or "Manual Market",
            "yes_id": args.yes_id,
            "no_id": args.no_id,
            "end_time": args.end_time,
        }

    market = await find_active_window()
    if market:
        return market

    print("No active market found via discovery. Provide --yes-id and --no-id to target a market manually.")
    return None


async def resolve_market_preset() -> Optional[Dict]:
    if PRESET_MARKET["yes_id"] and PRESET_MARKET["no_id"]:
        return {
            "title": PRESET_MARKET.get("title") or "Manual Market",
            "yes_id": PRESET_MARKET["yes_id"],
            "no_id": PRESET_MARKET["no_id"],
            "end_time": PRESET_MARKET.get("end_time"),
        }

    market = await find_active_window()
    if market:
        return market

    print("No active market found via discovery. Set PRESET_MARKET yes_id/no_id to target one manually.")
    return None


def parse_args() -> argparse.Namespace:
    # --- Strategy knobs (tweak defaults here or override via CLI) ---
    # Set USE_PRESET=True above to ignore CLI and use in-file settings.
    # fair-yes:   your fair value for YES; NO is 1 - fair_yes.
    # entry-edge: how cheap YES/NO must get vs fair to buy.
    # exit-edge:  how rich YES/NO must get vs fair to sell/trim.
    # order-size: per-trade size; max-position caps exposure per side.
    # side-mode:  trade both tokens or only YES/NO.
    # cooldown:   minimum seconds between trades on the same side.
    parser = argparse.ArgumentParser(description="Configurable Polymarket paper trading loop.")
    parser.add_argument("--yes-id", type=str, help="YES token id (skip discovery).")
    parser.add_argument("--no-id", type=str, help="NO token id (skip discovery).")
    parser.add_argument("--title", type=str, help="Optional title when providing token ids manually.")
    parser.add_argument("--end-time", type=str, help="Optional ISO end time for manual markets.")
    parser.add_argument("--fair-yes", type=float, default=0.5, help="Your fair value for YES (0-1). NO derives from 1-fair.")
    parser.add_argument("--entry-edge", "--edge", dest="entry_edge", type=float, default=0.02, help="How far below fair the ask must be to buy (price units).")
    parser.add_argument("--exit-edge", type=float, help="How far above fair the bid must be to sell (defaults to entry-edge).")
    parser.add_argument("--order-size", type=float, default=10.0, help="Size per trade (shares/contracts).")
    parser.add_argument("--max-position", type=float, default=100.0, help="Cap on open size per side (shares/contracts).")
    parser.add_argument("--side-mode", choices=["both", "yes-only", "no-only"], default="both", help="Trade both tokens or only YES/NO.")
    parser.add_argument("--cooldown", type=float, default=5.0, help="Seconds between trades per side.")
    parser.add_argument("--status-interval", type=float, default=10.0, help="How often to print PnL/status (seconds).")
    parser.add_argument("--run-seconds", type=float, help="Stop after N seconds (omit to run indefinitely).")
    parser.add_argument("--fee-bps", type=float, default=35.0, help="Per-trade fee in basis points (deducted from PnL).")
    return parser.parse_args()


async def main():
    if USE_PRESET:
        config = config_from_preset()
        market = await resolve_market_preset()
    else:
        args = parse_args()
        exit_edge = args.exit_edge if args.exit_edge is not None else args.entry_edge
        config = TraderConfig(
            fair_yes=args.fair_yes,
            entry_edge=args.entry_edge,
            exit_edge=exit_edge,
            order_size=args.order_size,
            max_position=args.max_position,
            cooldown=args.cooldown,
            status_interval=args.status_interval,
            run_seconds=args.run_seconds,
            fee_bps=args.fee_bps,
            side_mode=args.side_mode,
        )
        market = await resolve_market(args)

    if not market:
        return

    trader = PaperTrader(market, config)
    await trader.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Exiting paper trader")
