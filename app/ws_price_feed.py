from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import websockets

from .state_store import StateStore, utc_now_iso

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

logger = logging.getLogger(__name__)

# Inspired by market_watcher.py: WS level1 parsing + best bid/ask cache.

def _price_mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    return bid or ask


def _extract_price(item: Dict[str, Any]) -> list[tuple[str, Optional[float], Optional[float]]]:
    results: list[tuple[str, Optional[float], Optional[float]]] = []
    if item.get("event_type") == "level1":
        asset_id = item.get("asset_id")
        if asset_id:
            results.append((asset_id, item.get("best_bid"), item.get("best_ask")))
    elif item.get("event_type") == "price_change":
        for change in item.get("price_changes", []):
            asset_id = change.get("asset_id")
            if asset_id:
                results.append((asset_id, change.get("best_bid"), change.get("best_ask")))
    elif item.get("event_type") == "book":
        asset_id = item.get("asset_id")
        bids = item.get("bids", [])
        asks = item.get("asks", [])
        bid = bids[0]["price"] if bids else None
        ask = asks[0]["price"] if asks else None
        if asset_id:
            results.append((asset_id, bid, ask))
    return results


async def _subscribe(ws, asset_ids: list[str]) -> None:
    message = {"assets_ids": asset_ids, "type": "level1"}
    await ws.send(json.dumps(message))


async def run_ws_feed(state: StateStore, stop_event: asyncio.Event) -> None:
    backoff = 1.0
    while not stop_event.is_set():
        market = state.market
        if not market.yes_asset_id or not market.no_asset_id:
            await asyncio.sleep(5)
            continue

        asset_ids = [market.yes_asset_id, market.no_asset_id]
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                await _subscribe(ws, asset_ids)
                backoff = 1.0

                while not stop_event.is_set():
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        await ws.ping()
                        continue

                    data = json.loads(msg)
                    items = data if isinstance(data, list) else [data]

                    for item in items:
                        for asset_id, bid, ask in _extract_price(item):
                            side = "YES" if asset_id == market.yes_asset_id else "NO" if asset_id == market.no_asset_id else None
                            if not side:
                                continue
                            bid_value = float(bid) if bid is not None else None
                            ask_value = float(ask) if ask is not None else None
                            mid = _price_mid(bid_value, ask_value)
                            async with state.lock:
                                snapshot = state.price_cache[side]
                                if bid_value is not None:
                                    snapshot.best_bid = bid_value
                                if ask_value is not None:
                                    snapshot.best_ask = ask_value
                                snapshot.mid = mid
                                snapshot.last_update_utc = utc_now_iso()
        except Exception as exc:
            logger.info("WS reconnect: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
