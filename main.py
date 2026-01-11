import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from activity_poller import ActivityPoller
from copier import Copier
from dashboard import Dashboard, DashboardData
from market_session import MarketSession
from paper_broker import PaperBroker
from ws_price_feed import WsPriceFeed


OUTPUT_DIR = Path("output")


def _prompt_if_missing(value: Optional[str], prompt: str) -> str:
    if value:
        return value
    return input(prompt)


def _prompt_float(value: Optional[float], prompt: str) -> float:
    if value is not None:
        return value
    return float(input(prompt))


async def main() -> None:
    # Inspired by /mnt/data/paper_trading_ByBaran.py and /mnt/data/track_polymarket_activity.py
    # for orchestration patterns and async task layout.
    parser = argparse.ArgumentParser(description="Polymarket copy-trading simulator (paper trading only).")
    parser.add_argument("--watched-address", help="Ethereum address to monitor")
    parser.add_argument("--individual-share-rate", type=float, help="Share multiplier for copied trades")
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--max-events-buffer", type=int, default=200)
    parser.add_argument("--dashboard-refresh-seconds", type=float, default=1.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0, help="Optional slippage in basis points")
    parser.add_argument("--replay-path", type=Path, help="Replay events from ndjson file")
    args = parser.parse_args()

    watched_address = _prompt_if_missing(args.watched_address, "Watched address: ")
    share_rate = _prompt_float(args.individual_share_rate, "Individual share rate: ")

    OUTPUT_DIR.mkdir(exist_ok=True)
    session_path = OUTPUT_DIR / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "watched_address": watched_address,
                "individual_share_rate": share_rate,
                "poll_interval_seconds": args.poll_interval_seconds,
                "slippage_bps": args.slippage_bps,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )

    poller = ActivityPoller(
        watched_address,
        poll_interval=args.poll_interval_seconds,
        max_events_buffer=args.max_events_buffer,
        output_dir=OUTPUT_DIR,
    )
    price_feed = WsPriceFeed()
    broker = PaperBroker(output_dir=OUTPUT_DIR)
    copier = Copier(price_feed, broker, share_rate, slippage_bps=args.slippage_bps)
    market_session = MarketSession(price_feed, session_path=str(session_path))
    dashboard = Dashboard()

    await market_session.start()

    async def poll_loop() -> None:
        if args.replay_path:
            await poller.replay_from_file(args.replay_path)
        else:
            await poller.poll()

    async def copy_loop() -> None:
        while True:
            try:
                event = await asyncio.wait_for(poller.next_event(), timeout=0.5)
                await copier.handle_event(event)
            except asyncio.TimeoutError:
                pass
            await copier.check_pending()

    async def dashboard_loop() -> None:
        while True:
            broker.update_unrealized(price_feed.cache.yes.best_bid, price_feed.cache.no.best_bid)
            data = DashboardData(
                market=market_session.active_market,
                price_feed=price_feed,
                events=poller.latest_events(limit=20),
                copier=copier,
                broker=broker,
            )
            dashboard.render(data)
            await asyncio.sleep(args.dashboard_refresh_seconds)

    await asyncio.gather(poll_loop(), copy_loop(), dashboard_loop())


if __name__ == "__main__":
    asyncio.run(main())
