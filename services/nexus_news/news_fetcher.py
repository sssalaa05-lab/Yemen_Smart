"""
Nexus News — multi-source news aggregation with rate limiting and deduplication.

Integrates RSS feeds (free, no API key), NewsAPI and GNews (optional API keys),
maps headlines to affected currencies/assets, and provides a unified async
interface consumed by the polling loop in main.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from shared.http_client import new_client
import structlog
from pydantic import BaseModel, Field

from shared.models import NewsItem

log = structlog.get_logger(__name__)

# ── Currency / asset keyword mapping ─────────────────────────────────────────

CURRENCY_KEYWORDS: dict[str, list[str]] = {
    "USD": ["dollar", "usd", "fed", "fomc", "treasury", "us economy", "nonfarm", "cpi"],
    "EUR": ["euro", "eur", "ecb", "eurozone", "eu economy"],
    "GBP": ["pound", "gbp", "boe", "bank of england", "uk economy"],
    "JPY": ["yen", "jpy", "boj", "bank of japan", "japan economy"],
    "AUD": ["aussie", "aud", "rba", "australia economy"],
    "NZD": ["kiwi", "nzd", "rbnz", "new zealand economy"],
    "CAD": ["loonie", "cad", "boc", "canada economy", "oil price"],
    "CHF": ["franc", "chf", "snb", "swiss economy"],
    "XAU": ["gold", "xau", "precious metal", "bullion"],
    "BTC": ["bitcoin", "btc", "crypto"],
    "ETH": ["ethereum", "eth"],
    "SPX": ["s&p", "spx", "sp500", "wall street"],
}

# ── RSS sources (free — no API key required) ────────────────────────────────

RSS_SOURCES: list[dict[str, str]] = [
    {"url": "https://www.investing.com/rss/news_1.rss", "name": "Investing.com"},
    {"url": "https://www.investing.com/rss/news_25.rss", "name": "Investing.com FX"},
    {"url": "https://www.investing.com/rss/news_11.rss", "name": "Investing.com Commodities"},
    {"url": "https://www.marketwatch.com/rss/topstories", "name": "MarketWatch"},
]

_HIGH_IMPACT_KEYWORDS: set[str] = {
    "breaking", "urgent", "flash", "emergency", "crisis", "crash", "default",
    "rate decision", "rate cut", "rate hike", "intervention", "war", "strikes",
    "fed ", "fomc", "ecb ", "boj", "boe", "snb ", "nonfarm", "nfp",
    "cpi", "inflation", "gdp", "recession", "surprise", "shock",
}

_MARKET_WORDS: set[str] = {
    "dollar", "euro", "pound", "yen", "gold", "oil", "bitcoin", "crypto",
    "stocks", "bonds", "yields", "market", "markets", "fed", "central bank",
    "tariff", "trade", "inflation", "rate", "prices", "opec", "etf",
}


def _rss_impact(title: str) -> str:
    """Heuristic impact tier from the headline text."""
    t = title.lower()
    if any(kw in t for kw in _HIGH_IMPACT_KEYWORDS):
        return "high"
    if any(kw in t for kw in _MARKET_WORDS):
        return "medium"
    return "low"


def _score_rss_item(title: str) -> tuple[str, float]:
    """Return (sentiment_label, score) for a headline.

    Uses the keyword engine (deferred import avoids an import cycle with
    social_sentiment). FinBERT is deliberately not invoked here so the RSS
    poll never blocks on a model download; the analyze endpoint still uses it.
    """
    from .social_sentiment import _keyword_score

    kw = _keyword_score(title)
    if kw > 0.15:
        label = "bullish"
    elif kw < -0.15:
        label = "bearish"
    else:
        label = "neutral"
    return label, round(kw, 3)


def _parse_rss_date(raw: str | None) -> datetime:
    """Parse RSS pubDate — RFC822 ('Mon, 26 Oct 2026 …') or ISO-like
    ('2026-10-26 23:06:05', used by investing.com). Falls back to now."""
    if raw:
        raw = raw.strip()
        try:
            return parsedate_to_datetime(raw).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


# ── Rate limiter ─────────────────────────────────────────────────────────────

class _RateLimiter:
    """Token-bucket rate limiter per API source."""

    def __init__(self, calls_per_minute: int = 30):
        self._interval = 60.0 / calls_per_minute
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


# ── Fetcher ──────────────────────────────────────────────────────────────────

class NewsFetcher:
    """Aggregates headlines from NewsAPI and GNews with deduplication."""

    def __init__(
        self,
        newsapi_key: str = "",
        gnews_key: str = "",
        cache_ttl_sec: int = 120,
    ):
        self._newsapi_key = newsapi_key
        self._gnews_key = gnews_key
        self._cache_ttl = cache_ttl_sec

        self._newsapi_limiter = _RateLimiter(calls_per_minute=25)
        self._gnews_limiter = _RateLimiter(calls_per_minute=10)

        self._seen_hashes: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = new_client(timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── NewsAPI ──────────────────────────────────────────────────────────────

    async def fetch_newsapi(
        self, query: str, language: str = "en"
    ) -> list[NewsItem]:
        if not self._newsapi_key:
            log.warning("newsapi_key not configured — skipping NewsAPI")
            return []

        await self._newsapi_limiter.acquire()
        client = await self._get_client()

        params: dict[str, Any] = {
            "q": query,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": self._newsapi_key,
        }

        try:
            resp = await client.get(
                "https://newsapi.org/v2/everything", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                log.warning("newsapi_rate_limited", query=query)
            else:
                log.error("newsapi_error", status=exc.response.status_code)
            return []
        except httpx.HTTPError as exc:
            log.error("newsapi_http_error", error=str(exc))
            return []

        items: list[NewsItem] = []
        for article in data.get("articles", []):
            headline = (article.get("title") or "").strip()
            if not headline:
                continue

            published = article.get("publishedAt", "")
            ts = _parse_iso(published) if published else datetime.now(timezone.utc)

            items.append(
                NewsItem(
                    id=_headline_hash(headline),
                    revision_id=_news_revision_id(article.get("source", {}).get("name", "NewsAPI"), headline, ts),
                    headline=headline,
                    source=article.get("source", {}).get("name", "NewsAPI"),
                    timestamp=ts,
                    available_at=datetime.now(timezone.utc),
                    affected_currencies=_map_currencies(headline),
                )
            )

        log.debug("newsapi_fetched", query=query, count=len(items))
        return items

    # ── GNews ────────────────────────────────────────────────────────────────

    async def fetch_gnews(self, query: str) -> list[NewsItem]:
        if not self._gnews_key:
            log.warning("gnews_key not configured — skipping GNews")
            return []

        await self._gnews_limiter.acquire()
        client = await self._get_client()

        params: dict[str, Any] = {
            "q": query,
            "lang": "en",
            "max": 10,
            "token": self._gnews_key,
        }

        try:
            resp = await client.get(
                "https://gnews.io/api/v4/search", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                log.warning("gnews_rate_limited", query=query)
            else:
                log.error("gnews_error", status=exc.response.status_code)
            return []
        except httpx.HTTPError as exc:
            log.error("gnews_http_error", error=str(exc))
            return []

        items: list[NewsItem] = []
        for article in data.get("articles", []):
            headline = (article.get("title") or "").strip()
            if not headline:
                continue

            published = article.get("publishedAt", "")
            ts = _parse_iso(published) if published else datetime.now(timezone.utc)

            items.append(
                NewsItem(
                    id=_headline_hash(headline),
                    revision_id=_news_revision_id(article.get("source", {}).get("name", "GNews"), headline, ts),
                    headline=headline,
                    source=article.get("source", {}).get("name", "GNews"),
                    timestamp=ts,
                    available_at=datetime.now(timezone.utc),
                    affected_currencies=_map_currencies(headline),
                )
            )

        log.debug("gnews_fetched", query=query, count=len(items))
        return items

    # ── RSS (free sources) ───────────────────────────────────────────────────

    async def fetch_rss(self, source: dict[str, str]) -> list[NewsItem]:
        """Fetch and parse a single RSS feed. stdlib XML parser — no extra deps."""
        client = await self._get_client()
        try:
            resp = await client.get(
                source["url"],
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NexusNews/2.0",
                    "Accept": "application/rss+xml, application/xml, text/xml",
                },
                follow_redirects=True,  # MarketWatch 301s without this
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except (httpx.HTTPError, ET.ParseError) as exc:
            log.warning("rss_fetch_error", source=source["name"], error=str(exc))
            return []

        items: list[NewsItem] = []
        for entry in root.findall(".//item")[:30]:
            headline = (entry.findtext("title") or "").strip()
            if not headline:
                continue
            ts = _parse_rss_date(entry.findtext("pubDate"))
            label, score = _score_rss_item(headline)
            items.append(
                NewsItem(
                    id=_headline_hash(headline),
                    revision_id=_news_revision_id(source["name"], headline, ts, label, score),
                    headline=headline,
                    source=source["name"],
                    timestamp=ts,
                    available_at=datetime.now(timezone.utc),
                    impact=_rss_impact(headline),
                    sentiment=label,
                    affected_currencies=_map_currencies(headline),
                    finbert_score=score,
                )
            )

        log.debug("rss_fetched", source=source["name"], count=len(items))
        return items

    # ── Aggregator ───────────────────────────────────────────────────────────

    async def fetch_all(self, symbols: list[str]) -> list[NewsItem]:
        """Fetch from all sources for the given symbols, deduplicate, and return."""
        queries = _symbols_to_queries(symbols)
        tasks: list[asyncio.Task[list[NewsItem]]] = []

        for src in RSS_SOURCES:
            tasks.append(asyncio.create_task(self.fetch_rss(src)))
        for q in queries:
            tasks.append(asyncio.create_task(self.fetch_newsapi(q)))
            tasks.append(asyncio.create_task(self.fetch_gnews(q)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined: list[NewsItem] = []
        for res in results:
            if isinstance(res, BaseException):
                log.error("fetch_all_task_error", error=str(res))
                continue
            combined.extend(res)

        deduped = self._deduplicate(combined)
        log.info("fetch_all_complete", raw=len(combined), deduped=len(deduped))
        return deduped

    # ── Deduplication ────────────────────────────────────────────────────────

    def _deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        self._evict_stale()
        unique: list[NewsItem] = []
        now = time.monotonic()

        for item in items:
            h = _headline_hash(item.headline)
            if h not in self._seen_hashes:
                self._seen_hashes[h] = now
                unique.append(item)

        return unique

    def _evict_stale(self) -> None:
        now = time.monotonic()
        stale = [k for k, t in self._seen_hashes.items() if now - t > self._cache_ttl]
        for k in stale:
            del self._seen_hashes[k]


# ── Module-level helpers ─────────────────────────────────────────────────────

def _headline_hash(headline: str) -> str:
    normalised = headline.lower().strip()
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def _news_revision_id(source: str, headline: str, published_at: datetime, *derived: Any) -> str:
    """Stable content revision key; availability is recorded separately."""
    material = "|".join((source.strip().lower(), headline.strip(), published_at.isoformat(), *(str(x) for x in derived)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _map_currencies(text: str) -> list[str]:
    text_lower = text.lower()
    return [
        ccy
        for ccy, keywords in CURRENCY_KEYWORDS.items()
        if any(kw in text_lower for kw in keywords)
    ]


def _symbols_to_queries(symbols: list[str]) -> list[str]:
    """Convert trading symbols like EURUSD into search-friendly queries."""
    queries: set[str] = set()
    for sym in symbols:
        sym_upper = sym.upper().replace("/", "")
        if len(sym_upper) == 6:
            queries.add(sym_upper[:3])
            queries.add(sym_upper[3:])
        else:
            queries.add(sym_upper)

    keyword_map: dict[str, str] = {
        "USD": "US dollar economy",
        "EUR": "Euro eurozone economy",
        "GBP": "British pound economy",
        "JPY": "Japanese yen economy",
        "AUD": "Australian dollar economy",
        "NZD": "New Zealand dollar economy",
        "CAD": "Canadian dollar economy",
        "CHF": "Swiss franc economy",
        "XAU": "gold price",
        "BTC": "bitcoin crypto",
        "ETH": "ethereum crypto",
    }
    return [keyword_map.get(q, q) for q in queries]


def _parse_iso(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
