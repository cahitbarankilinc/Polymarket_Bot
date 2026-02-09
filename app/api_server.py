from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from .config import AppConfig, save_session_config
from .state_store import StateStore


def _parse_config(payload: dict) -> AppConfig:
    return AppConfig(**payload)


STATIC_DIR = Path(__file__).parent / "static"


def create_app(state: StateStore) -> web.Application:
    app = web.Application()

    async def get_index(request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "dashboard.html")

    async def get_health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def get_state(request: web.Request) -> web.Response:
        snapshot = await state.snapshot()
        return web.json_response(snapshot)

    async def get_events(request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", 20))
        events = await state.list_events(limit)
        return web.json_response({"events": events})

    async def get_orders(request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", 50))
        orders = await state.list_orders(limit)
        return web.json_response({"orders": orders})

    async def post_config(request: web.Request) -> web.Response:
        payload = await request.json()
        config = _parse_config(payload)
        state.update_config(config)
        save_session_config(config)
        return web.json_response({"status": "ok", "config": config.to_dict()})

    app.router.add_get("/", get_index)
    app.router.add_get("/dashboard", get_index)
    app.router.add_static("/static/", STATIC_DIR)
    app.router.add_get("/state", get_state)
    app.router.add_get("/events", get_events)
    app.router.add_get("/orders", get_orders)
    app.router.add_post("/config", post_config)
    app.router.add_get("/health", get_health)

    return app
