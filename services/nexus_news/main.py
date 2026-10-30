"""
Nexus News — FastAPI service (Service 4: News + NLP).

Provides endpoints for latest news, economic calendar, sentiment analysis,
and free-form text analysis.  Background tasks poll news sources every 30 s
and the economic calendar every 5 min, publishing NewsAlertEvent to Redis
when high-impact news is detected.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from shared.constants import (
    HEARTBEAT_INTERVAL_SEC,
    REDIS_KEY_PREFIX,
    RedisStream,
    STREAM_MAX_LEN,
)
from shared.events import NewsAlertEvent
from shared.models import CalendarEvent, NewsItem
from shared.source_revision_client import submit_source_revisions

from .calendar_parser import CalendarParser
from .news_fetcher import NewsFetcher
from .social_sentiment import SentimentResult, SocialSentiment

# ── Logging ──────────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_config().get("min_level", 20)  # INFO
    ),
)

from shared import setup_logger as _setup_logger
_setup_logger("nexus-news")
log = structlog.get_logger("nexus_news")

# ── Configuration ────────────────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
GNEWS_KEY = os.getenv("GNEWS_KEY", "")
USE_FINBERT = os.getenv("USE_FINBERT", "true").lower() == "true"
NEWS_POLL_SEC = int(os.getenv("NEWS_POLL_SEC", "30"))
CALENDAR_POLL_SEC = int(os.getenv("CALENDAR_POLL_SEC", "300"))
NEWS_CACHE_KEY = f"{REDIS_KEY_PREFIX}news:latest"
NEWS_CACHE_TTL = int(os.getenv("NEWS_CACHE_TTL_SEC", "7200"))
NEWS_BUFFER_CAP = int(os.getenv("NEWS_BUFFER_CAP", "80"))
SOURCE_ARCHIVE_ENABLED = len(os.getenv("NEXUS_INTERNAL_SERVICE_TOKEN", "").strip()) >= 32

DEFAULT_SYMBOLS = [
    "XAUUSD",
]

# ── Shared state ─────────────────────────────────────────────────────────────

_redis: aioredis.Redis | None = None
_fetcher: NewsFetcher | None = None
_calendar: CalendarParser | None = None
_sentiment: SocialSentiment | None = None

_latest_news: list[NewsItem] = []
_latest_calendar: list[CalendarEvent] = []
_bg_tasks: list[asyncio.Task[None]] = []
_pending_source_revisions: dict[tuple[str, str, str, str], dict[str, Any]] = {}

# ── Request / response schemas ───────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str
    symbol: str | None = None


class AnalyzeResponse(BaseModel):
    text: str
    keyword_score: float
    finbert_score: float
    combined_score: float
    affected_currencies: list[str]


class SentimentResponse(BaseModel):
    symbol: str
    social_score: float
    reddit: dict[str, Any] = Field(default_factory=dict)
    twitter: dict[str, Any] = Field(default_factory=dict)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _fetcher, _calendar, _sentiment  # noqa: PLW0603

    log.info("nexus_news_starting", port=8005)
    if not SOURCE_ARCHIVE_ENABLED:
        log.warning(
            "source_revision_archive_disabled",
            reason="NEXUS_INTERNAL_SERVICE_TOKEN missing or shorter than 32 characters",
        )

    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    _fetcher = NewsFetcher(newsapi_key=NEWSAPI_KEY, gnews_key=GNEWS_KEY)
    _calendar = CalendarParser()
    _sentiment = SocialSentiment(use_finbert=USE_FINBERT)

    # Seed the rolling buffer from the Redis cache so a service restart does
    # not blank the dashboard feed until the next poll.
    try:
        raw = await _redis.get(NEWS_CACHE_KEY)
        if raw:
            _latest_news = [
                NewsItem.model_validate(x) for x in json.loads(raw)
            ]
            log.info("news_cache_seeded", count=len(_latest_news))
    except Exception as exc:
        log.warning("news_cache_seed_error", error=str(exc))

    _bg_tasks.append(asyncio.create_task(_news_poll_loop()))
    _bg_tasks.append(asyncio.create_task(_calendar_poll_loop()))
    _bg_tasks.append(asyncio.create_task(_heartbeat_loop()))

    # News Sentinel (Fase 4)
    from .sentinel import sentinel_loop
    _sentinel_poll = int(os.getenv("SENTINEL_POLL_SEC", "60"))
    _bg_tasks.append(asyncio.create_task(
        sentinel_loop(_redis, fetcher=_fetcher, calendar=_calendar, poll_sec=_sentinel_poll)
    ))

    log.info("nexus_news_started")
    yield

    log.info("nexus_news_shutting_down")
    for t in _bg_tasks:
        t.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)

    if _fetcher:
        await _fetcher.close()
    if _calendar:
        await _calendar.close()
    if _redis:
        await _redis.aclose()

    log.info("nexus_news_stopped")


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus News",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    redis_ok = False
    if _redis:
        try:
            await _redis.ping()
            redis_ok = True
        except Exception:
            pass

    return {
        "service": "nexus-news",
        "status": "healthy" if redis_ok else "degraded",
        "redis": redis_ok,
        "news_cache_size": len(_latest_news),
        "calendar_cache_size": len(_latest_calendar),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /api/news/latest ────────────────────────────────────────────────────

@app.get("/api/news/latest", response_model=list[NewsItem])
async def get_latest_news(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None),
):
    items = _latest_news
    if symbol:
        sym_upper = symbol.upper()
        items = [
            n for n in items
            if sym_upper in n.affected_currencies
            or sym_upper[:3] in n.affected_currencies
            or sym_upper[3:] in n.affected_currencies
        ]
    return items[:limit]


# ── GET /api/news/calendar ──────────────────────────────────────────────────

@app.get("/api/news/calendar", response_model=list[CalendarEvent])
async def get_calendar(
    minutes: int = Query(default=1440, ge=1, le=10080),
    impact: str | None = Query(default=None),
):
    if not _calendar:
        raise HTTPException(503, "Calendar parser not initialised")

    events = await _calendar.get_upcoming_events(minutes=minutes)
    if impact:
        events = [e for e in events if e.impact == impact.lower()]
    return events


# ── GET /api/news/sentiment/{symbol} ────────────────────────────────────────

@app.get("/api/news/sentiment/{symbol}", response_model=SentimentResponse)
async def get_sentiment(symbol: str):
    if not _sentiment:
        raise HTTPException(503, "Sentiment analyser not initialised")

    # SocialSentiment exposes aggregate_social_sentiment(); the per-platform
    # fetch_* helpers were removed, so derive the overall score from that and
    # return neutral per-platform placeholders (the dashboard reads social_score).
    try:
        overall = await _sentiment.aggregate_social_sentiment(symbol)
    except Exception:
        log.warning("sentiment.aggregate_failed", symbol=symbol)
        overall = 0.0

    neutral = {"score": 0.0, "volume": 0, "source": "unavailable"}
    return SentimentResponse(
        symbol=symbol.upper(),
        social_score=round(float(overall or 0.0), 4),
        reddit=neutral,
        twitter=neutral,
    )


# ── POST /api/news/analyze ──────────────────────────────────────────────────

@app.post("/api/news/analyze", response_model=AnalyzeResponse)
async def analyze_text(req: AnalyzeRequest):
    from .news_fetcher import _map_currencies
    from .social_sentiment import _finbert_score, _keyword_score

    kw = _keyword_score(req.text)
    fb = await _finbert_score(req.text)
    combined = (kw * 0.4 + fb * 0.6) if fb != 0.0 else kw
    currencies = _map_currencies(req.text)

    return AnalyzeResponse(
        text=req.text,
        keyword_score=round(kw, 4),
        finbert_score=round(fb, 4),
        combined_score=round(combined, 4),
        affected_currencies=currencies,
    )


# ── Sentinel endpoints (Fase 4) ───────────────────────────────────────────────

@app.get("/api/news/sentinel/alerts")
async def get_sentinel_alerts(limit: int = Query(default=20, ge=1, le=50)):
    """Structured impact alerts from the news sentinel."""
    if not _redis:
        raise HTTPException(503, "Redis not initialised")
    try:
        raw = await _redis.lrange("nexus:news:sentinel:alerts", 0, limit - 1)
        return {"alerts": [json.loads(x) for x in raw], "count": len(raw)}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/news/sentinel/blackout")
async def get_blackout_status():
    """Current blackout window status for signal quality gate."""
    if not _redis:
        raise HTTPException(503, "Redis not initialised")
    try:
        raw = await _redis.get("nexus:news:sentinel:blackout")
        if raw:
            return json.loads(raw)
        return {"active": False, "reason": "no scan yet", "events": [], "ends_at": None}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/news/sentinel/status")
async def get_sentinel_status():
    """Status of the news sentinel service."""
    if not _redis:
        raise HTTPException(503, "Redis not initialised")
    try:
        last_scan = await _redis.get("nexus:news:sentinel:last_scan")
        blackout_raw = await _redis.get("nexus:news:sentinel:blackout")
        alert_count = await _redis.llen("nexus:news:sentinel:alerts")
        blackout = json.loads(blackout_raw) if blackout_raw else {}
        return {
            "last_scan": last_scan,
            "total_alerts": alert_count,
            "blackout_active": blackout.get("active", False),
            "blackout_reason": blackout.get("reason", ""),
        }
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


# ── Background: news polling ────────────────────────────────────────────────

def _merge_news(
    existing: list[NewsItem], incoming: list[NewsItem], cap: int
) -> list[NewsItem]:
    """Rolling merge: dedupe by id, newest first, capped."""
    first_observed = {
        ((item.provider or item.source).strip().lower(), item.revision_id): item.available_at
        for item in existing
        if item.revision_id and item.available_at is not None
    }
    for item in incoming:
        provider_revision = ((item.provider or item.source).strip().lower(), item.revision_id)
        if provider_revision in first_observed:
            item.available_at = first_observed[provider_revision]
    seen: set[tuple[str, str]] = set()
    merged: list[NewsItem] = []
    for item in sorted(
        [*incoming, *existing], key=lambda n: n.timestamp, reverse=True
    ):
        key = (
            (item.provider or item.source).strip().lower(),
            item.source_record_id or item.id or item.headline.lower().strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged[:cap]


async def _write_news_cache(items: list[NewsItem]) -> None:
    """Publish the rolling buffer to nexus:news:latest — the key nexus-api's
    /api/news endpoint serves to the dashboard. TTL keeps stale news out."""
    if not _redis or not items:
        return
    try:
        payload = json.dumps(
            [item.model_dump(mode="json") for item in items]
        )
        await _redis.set(NEWS_CACHE_KEY, payload, ex=NEWS_CACHE_TTL)
    except Exception as exc:
        log.error("news_cache_write_error", error=str(exc))


def _news_revision_record(item: NewsItem) -> dict[str, Any] | None:
    if not item.available_at or not item.source.strip():
        return None
    provider_id = (item.source_record_id or "").strip()
    fallback_id = item.id or hashlib.sha256(item.headline.encode("utf-8")).hexdigest()[:24]
    identity_material = provider_id or fallback_id
    entity_id = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()[:32]
    payload = {
        "headline": item.headline,
        "source": item.source,
        "impact": item.impact,
        "derived_sentiment": item.sentiment,
        "derived_score": item.finbert_score,
        "affected_currencies": list(item.affected_currencies),
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }
    revision_id = item.revision_id or hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return {
        "dataset": "news",
        "provider": item.provider or item.source,
        "entity_id": entity_id,
        "revision_id": revision_id,
        "source_record_id": provider_id or None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "available_at": item.available_at.isoformat(),
        "identity_quality": "provider" if provider_id else "derived",
        "quality_status": "observed",
        "schema_version": 1,
        "payload": payload,
    }


def _calendar_revision_record(event: CalendarEvent) -> dict[str, Any] | None:
    if not event.available_at or not event.source.strip():
        return None
    event_id = event.event_id.strip()
    if not event_id:
        event_id = hashlib.sha256(
            f"{event.source}|{event.currency}|{event.event_name}|{event.timestamp.isoformat()}".encode("utf-8")
        ).hexdigest()[:32]
    revision_id = event.revision_id or hashlib.sha256(
        json.dumps(
            {"event_id": event_id, "impact": event.impact, "forecast": event.forecast,
             "previous": event.previous, "actual": event.actual},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:32]
    payload = {
        "event_name": event.event_name,
        "currency": event.currency,
        "impact": event.impact,
        "forecast": event.forecast,
        "previous": event.previous,
        "actual": event.actual,
        "source": event.source,
    }
    return {
        "dataset": "economic",
        "provider": event.source,
        "entity_id": event_id,
        "revision_id": revision_id,
        "source_record_id": event.event_id or None,
        "event_time": event.timestamp.isoformat(),
        "available_at": event.available_at.isoformat(),
        "currency": event.currency,
        "identity_quality": "provider" if event.event_id else "derived",
        "quality_status": "observed",
        "schema_version": 1,
        "payload": payload,
    }


def _queue_source_revision(record: dict[str, Any] | None) -> None:
    if not record:
        return
    key = (record["dataset"], record["provider"], record["entity_id"], record["revision_id"])
    _pending_source_revisions.setdefault(key, record)


async def _flush_source_revision_queue() -> None:
    if not SOURCE_ARCHIVE_ENABLED or not _pending_source_revisions:
        return
    snapshot = list(_pending_source_revisions.items())
    try:
        await submit_source_revisions(
            [record for _, record in snapshot], caller_service="nexus-news",
        )
    except Exception as exc:
        log.warning("source_revision_archive_retry_pending", count=len(snapshot), error=str(exc))
        return
    for key, _ in snapshot:
        _pending_source_revisions.pop(key, None)


async def _news_poll_loop() -> None:
    global _latest_news  # noqa: PLW0603
    log.info("news_poll_started", interval_sec=NEWS_POLL_SEC)
    seeded_pending = False

    while True:
        try:
            if SOURCE_ARCHIVE_ENABLED and not seeded_pending:
                for cached_item in _latest_news:
                    _queue_source_revision(_news_revision_record(cached_item))
                seeded_pending = True
            if _fetcher:
                items = await _fetcher.fetch_all(DEFAULT_SYMBOLS)
                if items:
                    _latest_news = _merge_news(
                        _latest_news, items, NEWS_BUFFER_CAP
                    )
                    await _publish_high_impact_news(items)
                    await _write_news_cache(_latest_news)
                    if SOURCE_ARCHIVE_ENABLED:
                        for item in items:
                            _queue_source_revision(_news_revision_record(item))
                    log.info(
                        "news_poll_ok",
                        fetched=len(items),
                        total=len(_latest_news),
                    )
            await _flush_source_revision_queue()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("news_poll_error", error=str(exc))

        await asyncio.sleep(NEWS_POLL_SEC)


async def _publish_high_impact_news(items: list[NewsItem]) -> None:
    """Publish NewsAlertEvent to Redis for items with high-impact indicators."""
    if not _redis:
        return

    high_impact_keywords = {
        "breaking", "urgent", "flash", "emergency", "rate decision",
        "surprise", "shock", "crisis", "crash", "surge",
    }

    for item in items:
        headline_lower = item.headline.lower()
        is_high = (
            item.impact == "high"
            or any(kw in headline_lower for kw in high_impact_keywords)
        )
        if not is_high:
            continue

        event = NewsAlertEvent(
            source="nexus-news",
            headline=item.headline,
            source_name=item.source,
            impact=item.impact,
            sentiment=item.sentiment,
            affected_currencies=item.affected_currencies,
            finbert_score=item.finbert_score,
        )

        try:
            await _redis.xadd(
                RedisStream.NEWS_ALERT,
                event.to_stream_dict(),
                maxlen=STREAM_MAX_LEN,
            )
            log.info(
                "news_alert_published",
                headline=item.headline[:80],
                impact=item.impact,
            )
        except Exception as exc:
            log.error("news_alert_publish_error", error=str(exc))


# ── Background: calendar polling ─────────────────────────────────────────────

async def _calendar_poll_loop() -> None:
    global _latest_calendar  # noqa: PLW0603
    log.info("calendar_poll_started", interval_sec=CALENDAR_POLL_SEC)

    while True:
        try:
            if _calendar:
                events = await _calendar.fetch_calendar()
                if events:
                    _latest_calendar = sorted(
                        events, key=lambda e: e.timestamp,
                    )
                    if SOURCE_ARCHIVE_ENABLED:
                        for event in events:
                            _queue_source_revision(_calendar_revision_record(event))
                    log.info("calendar_poll_ok", count=len(events))
            await _flush_source_revision_queue()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("calendar_poll_error", error=str(exc))

        await asyncio.sleep(CALENDAR_POLL_SEC)


# ── Background: heartbeat ───────────────────────────────────────────────────

async def _heartbeat_loop() -> None:
    while True:
        try:
            if _redis:
                await _redis.set(
                    "nexus:health:nexus-news",
                    datetime.now(timezone.utc).isoformat(),
                    ex=HEARTBEAT_INTERVAL_SEC * 3,
                )
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.nexus_news.main:app",
        host="0.0.0.0",
        port=8005,
        reload=True,
    )
