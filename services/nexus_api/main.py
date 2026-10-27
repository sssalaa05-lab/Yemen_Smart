"""
Nexus Trader — API Gateway.

Central HTTP + WebSocket gateway that the dashboard (and external clients)
talk to.  Every other micro-service is reachable only through this gateway
or through Redis Streams.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.constants import SERVICE_PORTS

from .deps import config_loader, duckdb, redis, ws_manager
from .routers import (
    agents,
    backtest,
    bridge,
    config,
    intelligence,
    intermarket,
    market,
    ml,
    news,
    notifications,
    performance,
    positions,
    regime,
    risk,
    strategies,
    system,
    trades,
)
from .websockets import (
    agents as ws_agents,
    news as ws_news,
    orders as ws_orders,
    positions as ws_positions,
    risk as ws_risk,
    ticks as ws_ticks,
)

from shared import setup_logger as _setup_logger
_setup_logger("nexus-api")
logger = structlog.get_logger(__name__)

_broadcaster_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]


async def _start_ws_broadcasters() -> None:
    from .websockets.ticks import tick_broadcaster
    from .websockets.agents import agent_broadcaster
    from .websockets.positions import position_broadcaster
    from .websockets.orders import order_broadcaster
    from .websockets.news import news_broadcaster
    from .websockets.risk import risk_broadcaster

    broadcasters = [
        tick_broadcaster(redis, ws_manager),
        agent_broadcaster(redis, ws_manager),
        position_broadcaster(redis, ws_manager),
        order_broadcaster(redis, ws_manager),
        news_broadcaster(redis, ws_manager),
        risk_broadcaster(redis, ws_manager),
    ]
    for coro in broadcasters:
        _broadcaster_tasks.append(asyncio.create_task(coro))


async def _wait_for_data_writer(timeout: float = 150.0) -> bool:
    """Poll nexus-data /health until the DuckDB writer is ready."""
    import time as _time

    import httpx as _httpx

    port = SERVICE_PORTS.get("nexus-data", 9001)
    url = f"http://127.0.0.1:{port}/health"
    deadline = _time.monotonic() + timeout
    async with _httpx.AsyncClient(timeout=2.0) as client:
        while _time.monotonic() < deadline:
            try:
                res = await client.get(url)
                if res.status_code == 200:
                    return True
            except _httpx.RequestError:
                pass
            await asyncio.sleep(3)
    return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.ws_manager = ws_manager
    app.state.duckdb_available = False
    await redis.connect()
    # nexus-data owns the DuckDB write lock. If we open our read-only
    # connection while the writer is down (respawn race), we block it from
    # ever starting. Wait for the writer's health first; degrade gracefully
    # if it never comes up (same as the previous init-failure path).
    if await _wait_for_data_writer():
        try:
            await duckdb.init_db()
            app.state.duckdb_available = True
        except Exception as exc:
            await logger.awarning(
                "api_gateway.duckdb_unavailable",
                error=str(exc),
            )
    else:
        await logger.awarning(
            "api_gateway.duckdb_skipped_writer_not_ready",
            hint="nexus-data did not become healthy in time — DuckDB read-only disabled",
        )
    config_loader.load_all()
    await _start_ws_broadcasters()
    await logger.ainfo("api_gateway.started", port=SERVICE_PORTS["nexus-api"])
    yield
    for task in _broadcaster_tasks:
        task.cancel()
    await asyncio.gather(*_broadcaster_tasks, return_exceptions=True)
    _broadcaster_tasks.clear()
    await redis.disconnect()
    await duckdb.close()
    await logger.ainfo("api_gateway.stopped")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Trader API Gateway",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "http://localhost:3100")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[DASHBOARD_ORIGIN, "http://localhost:3100", "http://127.0.0.1:3100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST routers ─────────────────────────────────────────────────────────────

app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(performance.router)
app.include_router(agents.router)
app.include_router(risk.router)
app.include_router(system.router)
app.include_router(news.router)
app.include_router(intermarket.router)
app.include_router(config.router)
app.include_router(market.router)
app.include_router(bridge.router)
app.include_router(strategies.router)
app.include_router(ml.router)
app.include_router(regime.router)
app.include_router(intelligence.router)
app.include_router(notifications.router)
app.include_router(backtest.router)


# ── Auth (dashboard login) ──────────────────────────────────────────────────
# The login page posts to /api/v2/auth/login. Gateway routes themselves are
# auth-free by design (LAN/dev tool), so this endpoint validates the PIN from
# NEXUS_PIN and returns an opaque demo token the frontend stores locally.

class _LoginPayload(BaseModel):
    username: str = "admin"
    password: str = ""


@app.post("/api/v2/auth/login", tags=["auth"])
async def auth_login(payload: _LoginPayload) -> dict:
    expected = os.getenv("NEXUS_PIN", "1234").strip()
    if not expected or payload.password.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = f"nexus.{secrets.token_urlsafe(24)}"
    return {
        "token": token,
        "token_type": "bearer",
        "user": {"username": payload.username or "admin", "role": "trader"},
    }

# ── WebSocket routers ────────────────────────────────────────────────────────

app.include_router(ws_ticks.router)
app.include_router(ws_agents.router)
app.include_router(ws_positions.router)
app.include_router(ws_orders.router)
app.include_router(ws_news.router)
app.include_router(ws_risk.router)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health_check() -> dict:
    redis_ok = await redis.health_check()
    return {
        "status": "healthy" if redis_ok else "degraded",
        "service": "nexus-api",
        "redis": "connected" if redis_ok else "disconnected",
        "duckdb": "connected" if app.state.duckdb_available else "unavailable",
    }


# ── Global error handler ────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    await logger.aexception(
        "unhandled_error", path=request.url.path, error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
