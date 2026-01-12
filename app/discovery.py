from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import aiohttp
import pytz

logger = logging.getLogger(__name__)

API_URL = "https://gamma-api.polymarket.com/public-search"
ET_TZ = pytz.timezone("America/New_York")

# Inspired by discovery.py: 15-minute market search via gamma-api public-search.

@dataclass
class MarketDiscoveryResult:
    title: str
    yes_id: str
    no_id: str
    start_time: str
    end_time: str
    condition_id: Optional[str]
    market_id: Optional[str]


def current_et() -> datetime:
    return datetime.now(ET_TZ)


def get_window_boundaries(now_et: Optional[datetime] = None) -> tuple[datetime, datetime]:
    now_et = now_et or current_et()
    minute = (now_et.minute // 15) * 15
    start = now_et.replace(minute=minute, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    return start, end


def title_variants(start: datetime) -> list[str]:
    date_str = start.strftime("%B %d").replace(" 0", " ")
    time_str = start.strftime("%I:%M%p").lstrip("0").upper()
    return [
        f"Bitcoin Up or Down {date_str} {time_str} ET",
        f"Bitcoin Up or Down - {date_str}, {time_str} ET",
        f"Bitcoin Up or Down - {date_str} {time_str} ET",
    ]


async def find_active_window(session: aiohttp.ClientSession) -> Optional[MarketDiscoveryResult]:
    now_et = current_et()
    start, end = get_window_boundaries(now_et)

    queries = title_variants(start) + title_variants(end)
    for query in queries:
        url = f"{API_URL}?q={quote_plus(query)}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    logger.info("Discovery API status %s for query %s", resp.status, query)
                    continue
                data = await resp.json()
        except Exception as exc:
            logger.info("Discovery error: %s", exc)
            continue

        events = data.get("events", [])
        for event in events:
            market = (event.get("markets") or [{}])[0]
            start_ts = market.get("eventStartTime") or event.get("startTime")
            end_ts = market.get("endDate") or event.get("endDate")
            if not start_ts or not end_ts:
                continue

            start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00")).astimezone(ET_TZ)
            end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00")).astimezone(ET_TZ)
            duration = (end_dt - start_dt).total_seconds()
            if duration > 1800:
                continue
            if not (start_dt <= now_et < end_dt):
                continue

            token_ids = json.loads(market.get("clobTokenIds", "[]"))
            if len(token_ids) < 2:
                continue

            return MarketDiscoveryResult(
                title=event.get("title", "BTC 15m"),
                yes_id=token_ids[0],
                no_id=token_ids[1],
                start_time=start_dt.astimezone(pytz.UTC).isoformat(),
                end_time=end_dt.astimezone(pytz.UTC).isoformat(),
                condition_id=market.get("conditionId"),
                market_id=market.get("questionID") or market.get("questionId"),
            )
    return None


async def discovery_loop(refresh_callback, stop_event: asyncio.Event) -> None:
    backoff = 5.0
    while not stop_event.is_set():
        try:
            async with aiohttp.ClientSession() as session:
                market = await find_active_window(session)
        except Exception as exc:
            logger.info("Discovery loop error: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        if market:
            await refresh_callback(market)
            backoff = 5.0
            await asyncio.sleep(5)
        else:
            await asyncio.sleep(30)
