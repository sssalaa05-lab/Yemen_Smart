"""
Bridge router — the external MT5 bridge (Windows) reaches Nexus through the
same origin the dashboard uses: /api/v2/bridge/* (proxy → nexus-data ingest,
heartbeat store, status read). The decision poll reuses the existing
/api/agents/decision/{symbol} route.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from ..deps import redis as _redis
from ..http_client import new_client

router = APIRouter(prefix="/api/v2/bridge", tags=["bridge"])

DATA_BASE = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/")
BRIDGE_TOKEN = os.getenv("NEXUS_BRIDGE_TOKEN", "").strip()

_BRIDGE_STATUS_KEY = "nexus:bridge:status"


def _auth(request: Request) -> None:
    if BRIDGE_TOKEN and request.headers.get("x-bridge-token") != BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid bridge token")


async def _proxy_ingest(request: Request, path: str) -> dict[str, Any]:
    _auth(request)
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    if BRIDGE_TOKEN:
        headers["x-bridge-token"] = BRIDGE_TOKEN
    try:
        async with new_client(timeout=15.0) as client:
            res = await client.post(f"{DATA_BASE}{path}", content=body, headers=headers)
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"data service unreachable: {exc}")


@router.post("/ticks")
async def ingest_ticks(request: Request) -> dict[str, Any]:
    """Proxy live ticks from the external bridge into nexus-data."""
    return await _proxy_ingest(request, "/api/data/ingest/ticks")


@router.post("/bars")
async def ingest_bars(request: Request) -> dict[str, Any]:
    """Proxy OHLCV bars from the external bridge into nexus-data."""
    return await _proxy_ingest(request, "/api/data/ingest/bars")


@router.post("/calendar")
async def ingest_calendar(request: Request) -> dict[str, Any]:
    """Proxy economic-calendar events (from the bridge's calendar dump) into
    nexus-data for the News Sentinel / dashboard."""
    return await _proxy_ingest(request, "/api/data/ingest/calendar")


@router.post("/heartbeat")
async def heartbeat(request: Request) -> dict[str, Any]:
    """Bridge liveness + enriched market-info snapshot (terminal, account,
    per-symbol details) — stored whole for the dashboard / diagnostics."""
    _auth(request)
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    body.pop("token", None)
    payload = {**body, "ts": datetime.now(timezone.utc).isoformat()}
    await _redis.cache_set(_BRIDGE_STATUS_KEY, payload, ttl_sec=180)
    return {"ok": True}


@router.get("/status")
async def status() -> dict[str, Any]:
    """Bridge liveness for the dashboard / diagnostics."""
    raw = await _redis.cache_get(_BRIDGE_STATUS_KEY)
    online = False
    if isinstance(raw, dict):
        ts = raw.get("ts")
        if ts:
            try:
                age = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(str(ts))
                ).total_seconds()
                online = age < 180
            except Exception:
                online = False
    return {"success": True, "online": online, "bridge": raw}
