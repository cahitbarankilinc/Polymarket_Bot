from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiohttp import web

from .activity_poller import run_activity_poller, run_replay_poller
from .api_server import create_app
from .config import load_session_config
from .discovery import MarketDiscoveryResult, discovery_loop
from .state_store import StateStore, utc_now_iso
from .ws_price_feed import run_ws_feed
from .copier import run_copy_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("polymarket_copy")


async def _apply_market(state: StateStore, market: MarketDiscoveryResult) -> None:
    async with state.lock:
        if state.market.market_id == market.market_id and state.market.yes_asset_id == market.yes_id:
            return
        state.market.market_id = market.market_id or market.condition_id
        state.market.market_name = market.title
        state.market.end_time = market.end_time
        state.market.yes_asset_id = market.yes_id
        state.market.no_asset_id = market.no_id
        state.market.last_refresh_utc = utc_now_iso()
        state.price_cache["YES"] = state.price_cache["YES"].__class__()
        state.price_cache["NO"] = state.price_cache["NO"].__class__()
    logger.info("Market updated: %s", market.title)


async def _start_api(state: StateStore, host: str = "0.0.0.0", port: int = 8765) -> web.AppRunner:
    app = create_app(state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("API server listening on %s:%s", host, port)
    return runner


async def main() -> None:
    config = load_session_config()
    state = StateStore(config)
    stop_event = asyncio.Event()

    runner = await _start_api(state)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(discovery_loop(lambda market: _apply_market(state, market), stop_event))
        tg.create_task(run_ws_feed(state, stop_event))
        tg.create_task(run_copy_engine(state, stop_event))
        tg.create_task(run_activity_poller(state, stop_event))
        tg.create_task(run_replay_poller(state, stop_event))

    await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down")
