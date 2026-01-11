import os
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.util import find_spec
from typing import Iterable, Optional

from activity_poller import NormalizedEvent
from copier import Copier
from market_session import MarketInfo
from paper_broker import PaperBroker
from ws_price_feed import WsPriceFeed


@dataclass
class DashboardData:
    market: Optional[MarketInfo]
    price_feed: WsPriceFeed
    events: Iterable[NormalizedEvent]
    copier: Copier
    broker: PaperBroker


class Dashboard:
    """Terminal dashboard rendering.

    Inspired by /mnt/data/market_watcher.py output formatting and events.ndjson newest-first display.
    """

    def __init__(self) -> None:
        self._use_rich = find_spec("rich") is not None
        self._console = None
        if self._use_rich:
            from rich.console import Console

            self._console = Console()

    def render(self, data: DashboardData) -> None:
        if self._use_rich and self._console:
            self._render_rich(data)
        else:
            self._render_plain(data)

    def _render_plain(self, data: DashboardData) -> None:
        os.system("clear")
        print(self._header_lines(data))
        print("\nRecent Activity:")
        for event in data.events:
            print(self._event_line(event))
        print("\nPaper Trading Summary:")
        for line in self._summary_lines(data):
            print(line)

    def _render_rich(self, data: DashboardData) -> None:
        from rich.panel import Panel
        from rich.table import Table

        header = "\n".join(self._header_lines(data))
        activity_table = Table(show_header=True, header_style="bold")
        activity_table.add_column("Time")
        activity_table.add_column("Type")
        activity_table.add_column("Side")
        activity_table.add_column("Outcome")
        activity_table.add_column("Price")
        activity_table.add_column("Shares")
        for event in data.events:
            activity_table.add_row(
                event.event_time,
                event.type or "-",
                event.side or "-",
                event.outcome or "-",
                f"{event.price:.4f}" if event.price is not None else "-",
                f"{event.size:.4f}" if event.size is not None else "-",
            )
        summary_table = Table(show_header=False)
        for line in self._summary_lines(data):
            left, _, right = line.partition(": ")
            summary_table.add_row(left, right)
        if self._console:
            self._console.clear()
            self._console.print(Panel(header, title="Market"))
            self._console.print(Panel(activity_table, title="Activity (Newest First)"))
            self._console.print(Panel(summary_table, title="Paper Trading KPI"))

    def _header_lines(self, data: DashboardData) -> list[str]:
        market = data.market
        now = datetime.now(timezone.utc)
        end_time = market.end_time.isoformat() if market else "-"
        remaining = "-"
        if market:
            delta = market.end_time - now
            remaining = str(delta).split(".")[0]
        yes_bid = data.price_feed.cache.yes.best_bid
        yes_ask = data.price_feed.cache.yes.best_ask
        no_bid = data.price_feed.cache.no.best_bid
        no_ask = data.price_feed.cache.no.best_ask
        lines = [
            f"WATCHING: {market.question if market else 'Scanning...'}",
            f"Ends at: {end_time} (in {remaining})",
            f"Market ID: {market.market_id if market else '-'}",
            f"YES Token: {market.yes_token_id if market else '-'} | NO Token: {market.no_token_id if market else '-'}",
            f"YES bid/ask: {yes_bid} / {yes_ask} | NO bid/ask: {no_bid} / {no_ask}",
        ]
        return lines

    @staticmethod
    def _event_line(event: NormalizedEvent) -> str:
        price = f"{event.price:.4f}" if event.price is not None else "-"
        size = f"{event.size:.4f}" if event.size is not None else "-"
        return f"{event.event_time} | {event.type} | {event.side} | {event.outcome} | {price} | {size}"

    def _summary_lines(self, data: DashboardData) -> list[str]:
        broker = data.broker
        stats = data.copier.stats
        total = stats.executed + stats.missed
        fill_rate = (stats.executed / total) if total else 0.0
        min_lat, avg_lat, max_lat = data.copier.latency_stats()
        lines = [
            f"total_trades_copied: {stats.executed}",
            f"total_trades_missed: {stats.missed}",
            f"copy_fill_rate: {fill_rate:.2%}",
            f"total_shares_bought_yes: {broker.pnl.total_shares_bought['YES']:.4f}",
            f"total_shares_bought_no: {broker.pnl.total_shares_bought['NO']:.4f}",
            f"total_shares_sold_yes: {broker.pnl.total_shares_sold['YES']:.4f}",
            f"total_shares_sold_no: {broker.pnl.total_shares_sold['NO']:.4f}",
            f"average_entry_price_yes: {broker.positions['YES'].avg_price:.4f}",
            f"average_entry_price_no: {broker.positions['NO'].avg_price:.4f}",
            f"total_spent_usd: {broker.pnl.total_spent:.4f}",
            f"total_received_usd: {broker.pnl.total_received:.4f}",
            f"realized_pnl: {broker.pnl.realized:.4f}",
            f"unrealized_pnl: {broker.pnl.unrealized:.4f}",
            f"total_pnl: {(broker.pnl.realized + broker.pnl.unrealized):.4f}",
            f"slippage_vs_source: {data.copier.slippage_avg():.6f}",
            f"latency_seconds(min/avg/max): {min_lat:.3f} / {avg_lat:.3f} / {max_lat:.3f}",
        ]
        return lines
