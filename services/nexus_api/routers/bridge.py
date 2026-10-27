"""
Bridge router — the external MT5 bridge (Windows) reaches Nexus through the
same origin the dashboard uses: /api/v2/bridge/* (proxy → nexus-data ingest,
heartbeat store, status read). The decision poll reuses the existing
/api/agents/decision/{symbol} route.
"""
from __future__ import annotations

import json
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


@router.post("/positions")
async def ingest_positions(request: Request) -> dict[str, Any]:
    """Receive open positions snapshot from the bridge.

    The bridge polls MT5 every BRIDGE_POSITIONS_POLL_SEC and POSTs the full
    list (empty array if no positions) so the dashboard can display
    broker-side reality alongside internal nexus records.
    """
    _auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    positions = body.get("positions", [])
    payload = {
        "positions": positions,
        "count": len(positions),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    # Cache the latest snapshot (TTL slightly longer than the bridge's poll)
    await _redis.cache_set("nexus:bridge:positions", payload, ttl_sec=120)
    return {"ok": True, "received": len(positions)}


@router.get("/positions")
async def get_positions_snapshot() -> dict[str, Any]:
    """Return the latest bridge-reported positions snapshot."""
    raw = await _redis.cache_get("nexus:bridge:positions")
    if not isinstance(raw, dict):
        return {"positions": [], "count": 0, "stale": True}
    return raw


@router.post("/execute")
async def request_execute(request: Request) -> dict[str, Any]:
    """Bridge signals a decision it wants the system to execute.

    In EXECUTE_VIA_API=true mode, the bridge POSTs the agent decision here
    instead of calling mt5.order_send directly. The system records the
    request (so the dashboard can show pending actions) and returns an ack.
    Actual order routing to MT5 still happens on the bridge side — this
    endpoint just centralizes the audit trail.

    Future: a background consumer could relay approved executes back to the
    bridge via a Redis stream, so the bridge becomes a pure executor.
    """
    _auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    # Required fields
    required = ("symbol", "verdict", "conviction")
    missing = [k for k in required if k not in body]
    if missing:
        raise HTTPException(400, f"missing fields: {missing}")

    # Append to a Redis list for audit (cap at 1000 entries)
    audit_entry = {
        **body,
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "received",
    }
    try:
        # Use the raw redis client to push to a list
        raw_redis = _redis._redis if hasattr(_redis, "_redis") else None
        if raw_redis is not None:
            await raw_redis.lpush("nexus:bridge:execute_log", json.dumps(audit_entry))
            await raw_redis.ltrim("nexus:bridge:execute_log", 0, 999)
    except Exception:
        pass  # audit is best-effort

    return {
        "ok": True,
        "acknowledged": True,
        "symbol": body["symbol"],
        "verdict": body["verdict"],
        "conviction": body["conviction"],
    }


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
