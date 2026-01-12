import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiohttp

from ws_price_feed import WsPriceFeed


GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"


@dataclass
class MarketInfo:
    market_id: str
    question: str
    end_time: datetime
    yes_token_id: str
    no_token_id: str


class MarketSession:
    """Manages discovery of 15-minute markets and websocket subscriptions.

    Inspired by /mnt/data/discovery.py (active window discovery) and /mnt/data/market_watcher.py
    (watcher status and live subscription lifecycle).
    """

    def __init__(self, price_feed: WsPriceFeed, session_path: Optional[str] = None) -> None:
        self.price_feed = price_feed
        self.active_market: Optional[MarketInfo] = None
        self._task: Optional[asyncio.Task] = None
        self.session_path = session_path

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                market = await self._discover_market()
                if market and (self.active_market is None or market.market_id != self.active_market.market_id):
                    self.active_market = market
                    self._update_session(market)
                    await self.price_feed.stop()
                    asyncio.create_task(self.price_feed.connect([market.yes_token_id, market.no_token_id]))
            except (aiohttp.ClientError, asyncio.TimeoutError):
                await asyncio.sleep(5)
            await asyncio.sleep(30)

    async def _discover_market(self) -> Optional[MarketInfo]:
        params = {"active": "true", "limit": 200, "offset": 0, "search": "Bitcoin"}
        async with aiohttp.ClientSession() as session:
            async with session.get(GAMMA_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=15)
        candidates = []
        for market in markets:
            end_time = market.get("endTime") or market.get("end_time")
            question = market.get("question") or ""
            if not end_time:
                continue
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            if "15" in question and "Bitcoin" in question and now <= end_dt <= window_end:
                tokens = market.get("tokens") or []
                yes_token = next((token for token in tokens if token.get("outcome") == "Yes"), None)
                no_token = next((token for token in tokens if token.get("outcome") == "No"), None)
                if yes_token and no_token:
                    candidates.append(
                        MarketInfo(
                            market_id=str(market.get("id")),
                            question=question,
                            end_time=end_dt,
                            yes_token_id=str(yes_token.get("token_id") or yes_token.get("id")),
                            no_token_id=str(no_token.get("token_id") or no_token.get("id")),
                        )
                    )
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.end_time)[0]

    def _update_session(self, market: MarketInfo) -> None:
        if not self.session_path:
            return
        try:
            content = Path(self.session_path)
            payload = {}
            if content.exists():
                payload = json.loads(content.read_text())
            payload.update(
                {
                    "active_market": {
                        "market_id": market.market_id,
                        "question": market.question,
                        "end_time": market.end_time.isoformat(),
                        "yes_token_id": market.yes_token_id,
                        "no_token_id": market.no_token_id,
                    }
                }
            )
            content.write_text(json.dumps(payload, indent=2))
        except (json.JSONDecodeError, OSError):
            return

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self.price_feed.stop()
