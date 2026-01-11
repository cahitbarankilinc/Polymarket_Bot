from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp

from polymarket_copytrader.sources.base import ActivitySource

logger = logging.getLogger(__name__)


class HttpPollingActivitySource(ActivitySource):
    def __init__(self, url: str, wallet: str, poll_interval: float = 3.0, headers: Optional[Dict[str, str]] = None) -> None:
        self.url = url
        self.wallet = wallet
        self.poll_interval = poll_interval
        self.headers = headers or {}

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            while True:
                try:
                    async with session.get(self.url) as response:
                        if response.status != 200:
                            logger.warning("Polling error %s", response.status)
                        else:
                            data = await response.json()
                            for item in self._extract_events(data):
                                yield item
                except Exception as exc:
                    logger.warning("Polling exception: %s", exc)
                await asyncio.sleep(self.poll_interval)

    def _extract_events(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                return [item for item in payload["data"] if isinstance(item, dict)]
            if "data" in payload and isinstance(payload["data"], dict):
                return [payload["data"]]
            return [payload]
        return []
