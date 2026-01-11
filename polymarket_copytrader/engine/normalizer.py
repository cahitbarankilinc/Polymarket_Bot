from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from polymarket_copytrader.models import CanonicalTradeEvent


KNOWN_SIDE_MAP = {
    "buy": "BUY",
    "sell": "SELL",
}


def _parse_iso_ts(value: str) -> Optional[datetime]:
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        if value > 1e12:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        parsed = _parse_iso_ts(value)
        if parsed:
            return parsed
    return datetime.now(tz=timezone.utc)


def _normalize_side(raw: Any) -> str:
    if not raw:
        return "BUY"
    if isinstance(raw, str):
        normalized = KNOWN_SIDE_MAP.get(raw.lower())
        return normalized or raw.upper()
    return "BUY"


def _extract_price(payload: Dict[str, Any]) -> Optional[float]:
    for key in ("price", "avgPrice", "avg_price", "fillPrice", "fill_price"):
        if key in payload and payload[key] is not None:
            return float(payload[key])
    return None


def _extract_shares(payload: Dict[str, Any]) -> Optional[float]:
    for key in ("shares", "size", "quantity", "qty"):
        if key in payload and payload[key] is not None:
            return float(payload[key])
    return None


def _extract_notional(payload: Dict[str, Any]) -> Optional[float]:
    for key in ("notional", "amount", "value"):
        if key in payload and payload[key] is not None:
            return float(payload[key])
    return None


def _extract_event_id(payload: Dict[str, Any]) -> Optional[str]:
    for key in (
        "txHash",
        "transactionHash",
        "transaction_hash",
        "event_id",
        "id",
        "trade_id",
        "fill_id",
    ):
        if key in payload and payload[key]:
            return str(payload[key])
    return None


def _event_hash(payload: Dict[str, Any]) -> str:
    payload_str = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()[:24]


def normalize_event(payload: Dict[str, Any], source: str) -> CanonicalTradeEvent:
    market_id = payload.get("market_id") or payload.get("marketId") or payload.get("market")
    if isinstance(market_id, dict):
        market_id = market_id.get("id") or market_id.get("slug")

    market_slug = payload.get("market_slug") or payload.get("marketSlug")
    if isinstance(payload.get("market"), dict) and not market_slug:
        market_slug = payload["market"].get("slug")

    question = payload.get("question")
    if isinstance(payload.get("market"), dict) and not question:
        question = payload["market"].get("question")

    asset_id = payload.get("asset_id") or payload.get("assetId")
    outcome = payload.get("outcome")
    side = _normalize_side(payload.get("side") or payload.get("action"))

    shares = _extract_shares(payload) or 0.0
    price = _extract_price(payload) or 0.0
    notional = _extract_notional(payload)
    if notional is None and price and shares:
        notional = price * shares

    event_ts = parse_timestamp(payload.get("timestamp") or payload.get("ts") or payload.get("createdAt"))

    event_id = _extract_event_id(payload)
    if not event_id:
        fingerprint = {
            "ts": event_ts.isoformat(),
            "market_id": market_id,
            "side": side,
            "shares": shares,
            "price": price,
        }
        event_id = _event_hash(fingerprint)

    wallet = payload.get("wallet") or payload.get("trader") or payload.get("address")
    if isinstance(wallet, dict):
        wallet = wallet.get("id") or wallet.get("address")

    return CanonicalTradeEvent(
        event_id=str(event_id),
        ts=event_ts,
        wallet=str(wallet) if wallet else "",
        market_id=str(market_id) if market_id is not None else None,
        market_slug=str(market_slug) if market_slug is not None else None,
        question=str(question) if question is not None else None,
        asset_id=str(asset_id) if asset_id is not None else None,
        side=side,
        outcome=str(outcome) if outcome is not None else None,
        shares=float(shares),
        price=float(price),
        notional=float(notional) if notional is not None else None,
        source=source,
        raw=payload,
    )
