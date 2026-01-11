import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional

import websockets


WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class PriceState:
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    last_update: Optional[float] = None


@dataclass
class MarketPriceCache:
    yes: PriceState = field(default_factory=PriceState)
    no: PriceState = field(default_factory=PriceState)


class WsPriceFeed:
    """Websocket price feed for YES/NO assets.

    Inspired by /mnt/data/paper_trading_ByBaran.py and /mnt/data/market_watcher.py (level1/book
    parsing and live price cache updates).
    """

    def __init__(self) -> None:
        self._asset_ids: list[str] = []
        self.cache = MarketPriceCache()
        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self, asset_ids: list[str]) -> None:
        self._asset_ids = asset_ids
        self._running = True
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    await self._subscribe()
                    backoff = 1
                    async for message in ws:
                        await self._handle_message(message)
            except (websockets.WebSocketException, OSError):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _subscribe(self) -> None:
        payload = {
            "type": "subscribe",
            "channel": "market",
            "asset_ids": self._asset_ids,
        }
        if self._ws:
            await self._ws.send(json.dumps(payload))

    async def _handle_message(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        event_type = data.get("event_type") or data.get("type")
        if event_type in {"level1", "price_change"}:
            await self._handle_level1(data)
        if event_type == "book":
            await self._handle_book(data)

    async def _handle_level1(self, data: dict) -> None:
        asset_id = data.get("asset_id") or data.get("assetId")
        if asset_id not in self._asset_ids:
            return
        best_bid = data.get("best_bid") or data.get("bestBid")
        best_ask = data.get("best_ask") or data.get("bestAsk")
        price_state = self._resolve_state(asset_id)
        if best_bid is not None:
            price_state.best_bid = float(best_bid)
        if best_ask is not None:
            price_state.best_ask = float(best_ask)
        price_state.last_update = asyncio.get_event_loop().time()

    async def _handle_book(self, data: dict) -> None:
        asset_id = data.get("asset_id") or data.get("assetId")
        if asset_id not in self._asset_ids:
            return
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        price_state = self._resolve_state(asset_id)
        if bids:
            price_state.best_bid = float(bids[0][0] if isinstance(bids[0], list) else bids[0].get("price"))
        if asks:
            price_state.best_ask = float(asks[0][0] if isinstance(asks[0], list) else asks[0].get("price"))
        price_state.last_update = asyncio.get_event_loop().time()

    def _resolve_state(self, asset_id: str) -> PriceState:
        if asset_id == self._asset_ids[0]:
            return self.cache.yes
        return self.cache.no
