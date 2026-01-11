from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

import websockets

from polymarket_copytrader.sources.base import ActivitySource

logger = logging.getLogger(__name__)


class WebsocketActivitySource(ActivitySource):
    def __init__(self, url: str, wallet: str, subscribe_message: Optional[dict[str, Any]] = None) -> None:
        self.url = url
        self.wallet = wallet
        self.subscribe_message = subscribe_message

    async def _connect(self) -> websockets.WebSocketClientProtocol:
        return await websockets.connect(self.url, ping_interval=20, ping_timeout=20)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        backoff = 1
        while True:
            try:
                async with await self._connect() as ws:
                    backoff = 1
                    if self.subscribe_message:
                        await ws.send(json.dumps(self.subscribe_message))
                    async for message in ws:
                        payload = self._parse_message(message)
                        if payload is None:
                            continue
                        yield payload
            except Exception as exc:
                logger.warning("Websocket error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _parse_message(self, message: Any) -> Optional[dict[str, Any]]:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        if isinstance(message, str):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.debug("Skipping non-json message: %s", message)
                return None
        elif isinstance(message, dict):
            payload = message
        else:
            return None

        if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
            payload = payload["data"]

        return payload
