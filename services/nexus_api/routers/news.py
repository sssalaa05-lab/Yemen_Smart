"""
News router — latest news feed, calendar events, and per-symbol sentiment.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query

from shared.models import CalendarEvent, NewsItem
from shared.redis_client import RedisClient

from ..deps import get_redis

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[NewsItem])
async def latest_news(
    limit: int = Query(50, ge=1, le=200),
    impact: str | None = Query(None, description="Filter by impact: low, medium, high"),
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    cached = await redis.cache_get("news:latest")
    if cached and isinstance(cached, list):
        items = cached
    else:
        items = []

    if impact:
        items = [n for n in items if n.get("impact") == impact]
    return items[:limit]


@router.get("/calendar", response_model=list[CalendarEvent])
async def economic_calendar(
    currency: str | None = Query(None),
    impact: str | None = Query(None),
    redis: RedisClient = Depends(get_redis),
) -> list[dict[str, Any]]:
    """Merged calendar feed: MT5 economic calendar (via bridge EA, authoritative
    broker data) first, then any external-source events not already covered."""
    from datetime import datetime as _dt

    events: list[dict[str, Any]] = []

    # 1) MT5 calendar stored by the bridge ingest (bare key, no prefix).
    mt5_raw = await redis.cache_get("nexus:calendar:mt5", prefix=False)
    if isinstance(mt5_raw, list):
        for e in mt5_raw:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            ts = None
            try:
                ts = _dt.fromisoformat(str(e.get("time", "")).replace("Z", "+00:00"))
            except ValueError:
                pass
            events.append({
                "event_name": str(e.get("name"))[:160],
                "currency": str(e.get("currency", "")).upper()[:8],
                "impact": str(e.get("importance", "low"))[:16],
                "forecast": None if e.get("forecast") is None else str(e.get("forecast")),
                "previous": None if e.get("previous") is None else str(e.get("previous")),
                "actual": None if e.get("actual") is None else str(e.get("actual")),
                "timestamp": ts or _dt.utcnow(),
                "source": "mt5",
            })

    # 2) External calendar cache (forexfactory/newsapi pipeline).
    cached = await redis.cache_get("news:calendar")
    if isinstance(cached, list):
        seen = {(e["event_name"], str(e["timestamp"])) for e in events}
        for e in cached:
            if isinstance(e, dict) and e.get("event_name"):
                key = (e.get("event_name"), str(e.get("timestamp")))
                if key not in seen:
                    events.append(e)

    if currency:
        events = [e for e in events if e.get("currency") == currency.upper()]
    if impact:
        events = [e for e in events if e.get("impact") == impact]
    events.sort(key=lambda e: str(e.get("timestamp") or ""))
    return events


@router.get("/sentiment/{symbol}")
async def symbol_sentiment(
    symbol: str,
    redis: RedisClient = Depends(get_redis),
) -> dict[str, Any]:
    cached = await redis.cache_get(f"news:sentiment:{symbol.upper()}")
    if cached and isinstance(cached, dict):
        return cached
    return {
        "symbol": symbol.upper(),
        "overall_sentiment": "neutral",
        "score": 0.0,
        "headlines_analyzed": 0,
        "sources": [],
    }
