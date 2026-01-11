from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from polymarket_copytrader.engine.copier import CopyEngine
from polymarket_copytrader.engine.normalizer import normalize_event
from polymarket_copytrader.engine.paper import PaperTrader
from polymarket_copytrader.engine.pricing import FeeModel
from polymarket_copytrader.engine.risk import RiskConfig, RiskManager
from polymarket_copytrader.models import CanonicalTradeEvent, CopyResult
from polymarket_copytrader.sources.http_source import HttpPollingActivitySource
from polymarket_copytrader.sources.ws_source import WebsocketActivitySource
from polymarket_copytrader.storage.logs import NdjsonLogger
from polymarket_copytrader.storage.state import StateStore

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket copy-trading (paper) bot")
    parser.add_argument("--wallet", required=True, help="Target wallet address")
    parser.add_argument("--multiplier", type=float, default=1.0, help="Scale factor for shares")
    parser.add_argument("--max_position", type=float, default=None)
    parser.add_argument("--max_notional_usd", type=float, default=None)
    parser.add_argument("--cooldown_ms", type=int, default=0)
    parser.add_argument("--slippage_bps", type=float, default=0.0)
    parser.add_argument("--fee_bps", type=float, default=0.0)
    parser.add_argument("--min_fee", type=float, default=0.0)
    parser.add_argument("--event_buffer_size", type=int, default=100)
    parser.add_argument("--output_dir", type=str, default="output")
    parser.add_argument("--events_ndjson", action="store_true", help="Enable events NDJSON logging")
    parser.add_argument("--trades_ndjson", action="store_true", help="Enable trades NDJSON logging")
    parser.add_argument("--state_size", type=int, default=10000)
    parser.add_argument("--ws_url", type=str, default="", help="Websocket URL (preferred)")
    parser.add_argument("--http_url", type=str, default="", help="HTTP polling URL (fallback)")
    parser.add_argument("--poll_interval", type=float, default=3.0)
    parser.add_argument("--dashboard", action="store_true", help="Launch Streamlit dashboard")
    parser.add_argument("--no_dashboard", action="store_true", help="Disable Streamlit dashboard")
    parser.add_argument("--allow_partial_sell", action="store_true", default=True)
    parser.add_argument("--deny_partial_sell", action="store_true", default=False)
    return parser.parse_args()


def build_source(args: argparse.Namespace):
    if args.ws_url:
        return WebsocketActivitySource(args.ws_url, args.wallet)
    if args.http_url:
        return HttpPollingActivitySource(args.http_url, args.wallet, poll_interval=args.poll_interval)
    raise ValueError("Either --ws_url or --http_url must be provided")


def should_include_event(event: CanonicalTradeEvent, target_wallet: str) -> bool:
    if not event.wallet:
        return False
    return event.wallet.lower() == target_wallet.lower()


def serialize_event(event: CanonicalTradeEvent) -> Dict[str, Any]:
    return {
        "event_id": event.event_id,
        "ts": event.ts.isoformat(),
        "wallet": event.wallet,
        "market_id": event.market_id,
        "market_slug": event.market_slug,
        "question": event.question,
        "asset_id": event.asset_id,
        "side": event.side,
        "outcome": event.outcome,
        "shares": event.shares,
        "price": event.price,
        "notional": event.notional,
        "source": event.source,
    }


def serialize_trade(result: CopyResult) -> Optional[Dict[str, Any]]:
    if not result.paper_trade:
        return None
    trade = result.paper_trade
    return {
        "trade_id": trade.trade_id,
        "ts": trade.ts.isoformat(),
        "market_id": trade.market_id,
        "market_slug": trade.market_slug,
        "outcome": trade.outcome,
        "side": trade.side,
        "shares": trade.shares,
        "price": trade.price,
        "notional": trade.notional,
        "fee": trade.fee,
        "status": trade.status,
        "user_event_id": trade.user_event_id,
    }


def write_dashboard_state(
    output_dir: Path,
    recent_events: deque[Dict[str, Any]],
    copy_engine: CopyEngine,
    multiplier: float,
    risk_config: RiskConfig,
) -> None:
    positions = {}
    for market_id, market in copy_engine.paper_trader.positions.items():
        positions[market_id] = {
            "YES": {"qty": market.yes.qty, "avg_cost": market.yes.avg_cost},
            "NO": {"qty": market.no.qty, "avg_cost": market.no.avg_cost},
        }

    metrics = copy_engine.paper_trader.metrics
    state = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "recent_events": list(recent_events),
        "metrics": {
            "total_spent": metrics.total_spent,
            "total_received": metrics.total_received,
            "total_volume": metrics.total_volume,
            "total_fees": metrics.total_fees,
            "realized_pnl": metrics.realized_pnl,
            "unrealized_pnl": metrics.unrealized_pnl,
            "total_pnl": metrics.realized_pnl + metrics.unrealized_pnl,
        },
        "positions": positions,
        "settings": {
            "multiplier": multiplier,
            "max_position": risk_config.max_position,
            "max_notional_usd": risk_config.max_notional_usd,
            "cooldown_ms": risk_config.cooldown_ms,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dashboard_state.json").write_text(json.dumps(state, indent=2))


def generate_report(output_dir: Path, paper_trader: PaperTrader) -> None:
    metrics = paper_trader.metrics
    lines = [
        "# Session Report",
        "",
        f"Generated: {datetime.now(tz=timezone.utc).isoformat()}",
        "",
        "## KPIs",
        f"- Total spent: {metrics.total_spent:.4f}",
        f"- Total received: {metrics.total_received:.4f}",
        f"- Total volume: {metrics.total_volume:.4f}",
        f"- Total fees: {metrics.total_fees:.4f}",
        f"- Realized PnL: {metrics.realized_pnl:.4f}",
        f"- Unrealized PnL: {metrics.unrealized_pnl:.4f}",
        f"- Total PnL: {metrics.realized_pnl + metrics.unrealized_pnl:.4f}",
        "",
        "## Positions",
    ]
    for market_id, market in paper_trader.positions.items():
        lines.append(f"### Market {market_id}")
        lines.append(f"- YES qty: {market.yes.qty:.4f} @ {market.yes.avg_cost:.4f}")
        lines.append(f"- NO qty: {market.no.qty:.4f} @ {market.no.avg_cost:.4f}")
        lines.append("")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.md").write_text("\n".join(lines))


def launch_dashboard(output_dir: Path) -> subprocess.Popen[str]:
    cmd = [
        "streamlit",
        "run",
        str(Path(__file__).parent / "dashboard.py"),
        "--",
        "--output-dir",
        str(output_dir),
    ]
    logger.info("Launching dashboard: %s", " ".join(cmd))
    return subprocess.Popen(cmd)


def setup_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "copytrader.log"
    handlers = [logging.StreamHandler(), logging.FileHandler(log_path)]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


async def run_copytrader(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    setup_logging(output_dir)

    state_store = StateStore(path=output_dir / "state.json", max_size=args.state_size)
    state_store.load()

    events_logger = NdjsonLogger(output_dir / "events.ndjson", enabled=args.events_ndjson)
    trades_logger = NdjsonLogger(output_dir / "trades.ndjson", enabled=args.trades_ndjson)

    fee_model = FeeModel(fee_bps=args.fee_bps, min_fee=args.min_fee)
    paper_trader = PaperTrader(fee_model)
    risk_config = RiskConfig(
        max_position=args.max_position,
        max_notional_usd=args.max_notional_usd,
        cooldown_ms=args.cooldown_ms,
        allow_partial_sell=not args.deny_partial_sell,
    )
    risk_manager = RiskManager(risk_config)

    recent_events: deque[Dict[str, Any]] = deque(maxlen=args.event_buffer_size)

    def on_trade(result: CopyResult) -> None:
        if result.paper_trade:
            payload = serialize_trade(result)
            if payload:
                trades_logger.append(payload)

    copy_engine = CopyEngine(
        multiplier=args.multiplier,
        slippage_bps=args.slippage_bps,
        risk_manager=risk_manager,
        paper_trader=paper_trader,
        on_trade=on_trade,
    )

    source = build_source(args)

    dashboard_proc: Optional[subprocess.Popen[str]] = None
    if args.dashboard and not args.no_dashboard:
        dashboard_proc = launch_dashboard(output_dir)

    stop_event = asyncio.Event()

    def _signal_handler(*_: Any) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        async for payload in source.events():
            if stop_event.is_set():
                break

            try:
                event = normalize_event(payload, "ws" if args.ws_url else "http")
            except Exception as exc:
                logger.warning("Failed to normalize event: %s", exc)
                continue

            if not should_include_event(event, args.wallet):
                continue

            if state_store.seen(event.event_id):
                continue

            state_store.add(event.event_id)
            events_logger.append(serialize_event(event))

            result = copy_engine.process(event)
            if result.paper_trade:
                recent_events.appendleft(
                    {
                        "ts": event.ts.isoformat(),
                        "market": event.market_slug or event.market_id,
                        "outcome": event.outcome,
                        "side": event.side,
                        "user_shares": event.shares,
                        "bot_shares": result.paper_trade.shares,
                        "price": result.paper_trade.price,
                        "notional": result.paper_trade.notional,
                        "status": result.paper_trade.status,
                    }
                )
            else:
                recent_events.appendleft(
                    {
                        "ts": event.ts.isoformat(),
                        "market": event.market_slug or event.market_id,
                        "outcome": event.outcome,
                        "side": event.side,
                        "user_shares": event.shares,
                        "bot_shares": 0.0,
                        "price": event.price,
                        "notional": event.notional or 0.0,
                        "status": result.reason or "ignored",
                    }
                )

            write_dashboard_state(output_dir, recent_events, copy_engine, args.multiplier, risk_config)
            state_store.save()

    finally:
        state_store.save()
        generate_report(output_dir, paper_trader)
        if dashboard_proc:
            dashboard_proc.terminate()


def main() -> None:
    args = parse_args()
    asyncio.run(run_copytrader(args))


if __name__ == "__main__":
    main()
