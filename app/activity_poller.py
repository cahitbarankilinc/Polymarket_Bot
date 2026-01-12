from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from .state_store import StateStore, utc_now_iso

ACTIVITY_URL = "https://data-api.polymarket.com/activity"
TRADES_URL = "https://data-api.polymarket.com/trades"

logger = logging.getLogger(__name__)

# Inspired by track_polymarket_activity.py: polling + dedup + ndjson logging.

def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _generate_event_id(raw: Dict[str, Any], source: str) -> str:
    tx_hash = raw.get("transactionHash") or raw.get("txHash") or raw.get("hash")
    if tx_hash:
        return str(tx_hash)
    event_time = raw.get("timestamp") or raw.get("createdAt") or raw.get("time") or raw.get("eventTime")
    market = raw.get("question") or raw.get("slug") or raw.get("market") or raw.get("marketId")
    side = raw.get("side") or raw.get("action") or ""
    price = raw.get("price") or raw.get("avgPrice") or ""
    size = raw.get("size") or raw.get("amount") or raw.get("shares") or ""
    return f"{source}:{event_time}|{market}|{side}|{price}|{size}"


def _normalize_event(raw: Dict[str, Any], source: str, seen_at: str) -> Dict[str, Any]:
    event_time = raw.get("timestamp") or raw.get("createdAt") or raw.get("time") or raw.get("eventTime")
    event_type = raw.get("type") or raw.get("eventType") or ("TRADE" if source == "trades" else None)
    side = raw.get("side") or raw.get("action")
    market = raw.get("question") or raw.get("slug") or raw.get("market") or raw.get("marketId")
    outcome = raw.get("outcome") or raw.get("outcomeName") or raw.get("token")
    price = _to_float(raw.get("price") or raw.get("avgPrice"))
    size = _to_float(raw.get("size") or raw.get("amount") or raw.get("shares"))
    value = _to_float(raw.get("value") or raw.get("valueUSD"))
    if value is None and price is not None and size is not None:
        value = round(price * size, 6)
    tx_hash = raw.get("transactionHash") or raw.get("txHash") or raw.get("hash")

    return {
        "event_id": _generate_event_id(raw, source),
        "seen_at_utc": seen_at,
        "event_time": event_time,
        "type": event_type,
        "side": side,
        "market": market,
        "outcome": outcome,
        "price": price,
        "size": size,
        "value_usd": value,
        "tx_hash": tx_hash,
        "raw_source": source,
    }


async def _fetch_endpoint(session: aiohttp.ClientSession, url: str, params: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status in (429, 500, 502, 503, 504):
                logger.warning("Backoff triggered for %s: HTTP %s", url, resp.status)
                return None
            if resp.status != 200:
                logger.warning("Unexpected status %s for %s", resp.status, url)
                return None
            payload = await resp.json()
    except Exception as exc:
        logger.warning("Request error for %s: %s", url, exc)
        return None

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "activities", "trades", "activity"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    logger.warning("Unrecognized response format for %s", url)
    return None


async def run_activity_poller(state: StateStore, stop_event: asyncio.Event) -> None:
    backoff = 1.0
    while not stop_event.is_set():
        config = state.config
        if config.replay_path:
            await asyncio.sleep(config.poll_interval_seconds)
            continue

        if not config.watched_address:
            await asyncio.sleep(config.poll_interval_seconds)
            continue

        params = {"user": config.watched_address, "limit": 50, "offset": 0}

        try:
            async with aiohttp.ClientSession() as session:
                activity, trades = await asyncio.gather(
                    _fetch_endpoint(session, ACTIVITY_URL, params),
                    _fetch_endpoint(session, TRADES_URL, params),
                )
        except Exception as exc:
            logger.warning("Activity poll error: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue

        backoff = 1.0
        seen_at = utc_now_iso()
        new_events = []

        for payload, source in ((activity, "activity"), (trades, "trades")):
            if not payload:
                continue
            for raw in payload:
                normalized = _normalize_event(raw, source, seen_at)
                event_id = normalized.get("event_id")
                if not event_id:
                    continue
                if event_id in state.seen_ids:
                    continue
                state.seen_ids.add(event_id)
                state.seen_queue.append(event_id)
                new_events.append(normalized)

        for event in sorted(new_events, key=lambda e: e.get("event_time") or ""):
            await state.add_event(event)

        state.save_state()
        await asyncio.sleep(config.poll_interval_seconds)


async def run_replay_poller(state: StateStore, stop_event: asyncio.Event) -> None:
    config = state.config
    if not config.replay_path:
        return

    logger.info("Replay mode enabled: %s", config.replay_path)
    try:
        with open(config.replay_path, "r", encoding="utf-8") as f:
            for line in f:
                if stop_event.is_set():
                    break
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                event.setdefault("seen_at_utc", utc_now_iso())
                event.setdefault("event_id", f"replay-{event.get('tx_hash') or event.get('event_time')}")
                await state.add_event(event)
                await asyncio.sleep(config.poll_interval_seconds)
    except FileNotFoundError:
        logger.warning("Replay file not found: %s", config.replay_path)
    except Exception as exc:
        logger.warning("Replay error: %s", exc)


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None
