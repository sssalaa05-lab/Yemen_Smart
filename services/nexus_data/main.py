"""
Nexus Data Service — FastAPI application.

Exposes tick / OHLCV query endpoints and manages the lifecycle of every
data-feed connector, the DuckDB store, and the Redis tick cache.
"""
from __future__ import annotations

import asyncio
import hmac
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.constants import RedisStream, SERVICE_PORTS, SUPPORTED_TIMEFRAMES
from shared.events import TickEvent, OHLCVEvent
from shared.models import Tick, OHLCV
from shared.nexus_trades import strategy_from_comment as _strategy_from_comment
from shared.redis_client import RedisClient

from .duckdb_store import DataStore
from .redis_cache import TickCache
from .mt5_connector import MT5Connector
from .ibkr_connector import IBKRConnector
from .ccxt_connector import CCXTConnector

from shared import setup_logger as _setup_logger
_setup_logger("nexus-data")
log = structlog.get_logger("nexus_data")

# ── Configuration from env ───────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DUCKDB_PATH = os.getenv("DUCKDB_PATH", "./data/nexus.duckdb")

MT5_LOGIN = int((os.getenv("MT5_LOGIN") or "0").strip() or "0")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")

IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))

CCXT_EXCHANGE = os.getenv("CCXT_EXCHANGE", "binance")
CCXT_API_KEY = os.getenv("CCXT_API_KEY", "")
CCXT_SECRET = os.getenv("CCXT_SECRET", "")

DEFAULT_BROKER = os.getenv("DEFAULT_BROKER", "mt5")
# Production default: MT5-only real data. Set NEXUS_DATA_SYNTHETIC_FALLBACK=1 only for offline dev.
SYNTHETIC_FALLBACK = os.getenv("NEXUS_DATA_SYNTHETIC_FALLBACK", "0").lower() in (
    "1",
    "true",
    "yes",
)

# Data source selector: "mt5" (default, broker terminal) | "yahoo" (free real
# prices via yfinance — slightly delayed, see _yahoo_feed_loop) .
DATA_SOURCE = os.getenv("NEXUS_DATA_SOURCE", "mt5").strip().lower()
BRIDGE_TOKEN = os.getenv("NEXUS_BRIDGE_TOKEN", "").strip()
INTERNAL_SERVICE_TOKEN = os.getenv("NEXUS_INTERNAL_SERVICE_TOKEN", "").strip()
_REVISION_INGEST_CALLERS = {"nexus-news", "nexus-features"}
YAHOO_POLL_SEC = float(os.getenv("NEXUS_YAHOO_POLL_SEC", "15"))

# Logical Nexus symbol → Yahoo ticker. Gold spot has no direct Yahoo ticker,
# so we use COMEX gold futures (GC=F) — tracks XAUUSD closely with a small
# futures basis. Forex pairs use the "...=X" indicative FX rate.
_YAHOO_SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
}


def _yahoo_symbol(symbol: str) -> str:
    """Map a Nexus logical symbol to its Yahoo Finance ticker."""
    s = symbol.upper()
    if s in _YAHOO_SYMBOL_MAP:
        return _YAHOO_SYMBOL_MAP[s]
    if len(s) == 6 and s.endswith("USD"):
        return f"{s}=X"
    return s

# Symbols to stream on startup (comma-separated env var); logical names (aliases → broker via MT5_SYMBOL_ALIASES).
STREAM_SYMBOLS = [
    s.strip().upper().replace("/", "")
    for s in os.getenv(
        "STREAM_SYMBOLS", "XAUUSD"
    ).split(",")
    if s.strip()
]

# ── Shared instances ─────────────────────────────────────────────────────────

redis_client = RedisClient(url=REDIS_URL)
data_store = DataStore(db_path=DUCKDB_PATH)
tick_cache = TickCache(redis_client)

mt5 = MT5Connector()
ibkr = IBKRConnector()
ccxt_conn = CCXTConnector()

_streaming_tasks: list[asyncio.Task] = []


def _base_price(symbol: str) -> float:
    s = symbol.upper()
    if s.startswith("XAU"):
        return 2350.0
    if s.startswith("BTC"):
        return 65000.0
    if "JPY" in s:
        return 155.0
    return 1.08


def _synthetic_tick(symbol: str) -> Tick:
    now = datetime.now(timezone.utc)
    seed = sum(ord(c) for c in symbol)
    base = _base_price(symbol)
    wiggle = math.sin(now.timestamp() / 60 + seed) * base * 0.0005
    bid = base + wiggle
    spread = 0.25 if symbol.startswith("XAU") else 0.00015
    return Tick(symbol=symbol, bid=bid, ask=bid + spread, timestamp=now)


def _synthetic_ohlcv(symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
    minutes = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
    }.get(timeframe, 15)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base = _base_price(symbol)
    amp = base * (0.0015 if not symbol.startswith("BTC") else 0.004)
    seed = sum(ord(c) for c in symbol + timeframe)
    out: list[OHLCV] = []
    for i in range(limit - 1, -1, -1):
        ts = now - timedelta(minutes=minutes * i)
        x = (limit - i + seed) / 8.0
        close = base + math.sin(x) * amp + math.sin(x / 3) * amp * 0.5
        open_ = base + math.sin(x - 0.2) * amp + math.sin((x - 0.2) / 3) * amp * 0.5
        high = max(open_, close) + amp * 0.2
        low = min(open_, close) - amp * 0.2
        out.append(OHLCV(
            symbol=symbol,
            timeframe=timeframe,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=100 + abs(math.sin(x)) * 900,
            timestamp=ts,
        ))
    return out


# ── Tick ingestion callback ──────────────────────────────────────────────────

async def _on_tick(tick: Tick) -> None:
    """Fan-out every incoming tick to cache, DuckDB, and Redis Stream."""
    try:
        await asyncio.gather(
            tick_cache.cache_tick(tick),
            data_store.insert_tick(tick),
            redis_client.publish_event(
                RedisStream.TICK_STREAM,
                TickEvent(
                    source="nexus-data",
                    symbol=tick.symbol,
                    bid=tick.bid,
                    ask=tick.ask,
                    spread=tick.spread,
                ),
            ),
        )
    except Exception:
        await log.aexception("tick_ingest_error", symbol=tick.symbol)


async def _trade_close_consumer() -> None:
    """Consume TradeCloseEvent from Redis Stream and persist to DuckDB.

    Bridges the gap between the executor (publishes close events) and the
    API gateway's trades table so the dashboard history page works.
    """
    import json as _json
    import uuid

    CONSUMER_GROUP = "nexus-data-trades-cg"
    CONSUMER_NAME = f"data-trade-worker-{uuid.uuid4().hex[:6]}"
    STREAM = RedisStream.TRADE_CLOSE

    await asyncio.sleep(5)

    try:
        await redis_client.r.xgroup_create(STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            await log.aexception("trade_consumer.group_create_failed")

    await log.ainfo("trade_consumer.started", stream=STREAM)

    while True:
        try:
            entries = await redis_client.r.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM: ">"},
                count=10,
                block=3000,
            )
            if not entries:
                continue

            for _stream_name, messages in entries:
                for msg_id, raw in messages:
                    try:
                        trade_id = raw.get("trade_id", raw.get("order_id", msg_id))
                        symbol = raw.get("symbol", "")
                        side = raw.get("side", "BUY")
                        entry_price = float(raw.get("entry_price", 0))
                        exit_price = float(raw.get("exit_price", 0))
                        pnl_pips = float(raw.get("pnl_pips", 0))
                        pnl_usd = float(raw.get("pnl_usd", 0))
                        rr_ratio = float(raw.get("rr_ratio", 0))
                        reason = raw.get("reason", "")

                        if not symbol:
                            await redis_client.r.xack(STREAM, CONSUMER_GROUP, msg_id)
                            continue

                        if exit_price == 0 and entry_price > 0 and pnl_pips != 0:
                            from shared.asset_specs import pips_to_price
                            signed = pnl_pips if side.upper() == "BUY" else -pnl_pips
                            exit_price = entry_price + pips_to_price(symbol, signed)
                        if exit_price == 0 and pnl_usd == 0 and pnl_pips == 0:
                            await redis_client.r.xack(STREAM, CONSUMER_GROUP, msg_id)
                            continue

                        now = datetime.now(timezone.utc)
                        opened_str = (
                            raw.get("opened_at")
                            or raw.get("data.opened_at")
                            or raw.get("timestamp")
                            or now.isoformat()
                        )
                        if not opened_str or opened_str == "0" or opened_str == "":
                            opened_str = now.isoformat()
                        try:
                            opened_at = datetime.fromisoformat(str(opened_str).replace("Z", "+00:00"))
                            if opened_at.tzinfo is None:
                                opened_at = opened_at.replace(tzinfo=timezone.utc)
                        except Exception:
                            opened_at = now
                        closed_at = now
                        # Broker clocks can drift/skew (server-time epochs); a
                        # future opened_at would store negative durations.
                        if opened_at > closed_at:
                            await log.awarning(
                                "trade_consumer.opened_after_closed",
                                trade_id=trade_id,
                                opened_at=str(opened_at),
                            )
                            opened_at = closed_at
                        duration_s = max(0.0, (closed_at - opened_at).total_seconds())

                        strategy = str(
                            raw.get("data.strategy", "")
                            or _strategy_from_comment(str(raw.get("data.source", "")))
                        )

                        await data_store.insert_trade(
                            trade_id=str(trade_id),
                            symbol=symbol,
                            side=side,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            pnl_pips=pnl_pips,
                            pnl_usd=pnl_usd,
                            rr_ratio=rr_ratio,
                            duration_s=duration_s,
                            session=raw.get("session", ""),
                            conviction=float(raw.get("conviction", 0)),
                            opened_at=opened_at,
                            closed_at=closed_at,
                            strategy=strategy,
                        )
                        await log.ainfo(
                            "trade_consumer.persisted",
                            trade_id=trade_id,
                            symbol=symbol,
                            side=side,
                            pnl_usd=pnl_usd,
                        )
                    except Exception:
                        await log.aexception("trade_consumer.process_error", msg_id=msg_id)
                    finally:
                        await redis_client.r.xack(STREAM, CONSUMER_GROUP, msg_id)

        except asyncio.CancelledError:
            break
        except Exception:
            await log.aexception("trade_consumer.loop_error")
            await asyncio.sleep(5)


OHLCV_POLL_SEC = int(os.getenv("NEXUS_OHLCV_POLL_SEC", "30"))
# Comma-separated list of timeframes to stream. Scalping needs M5 (primary
# decision TF) plus M15/H1 (confirmation TFs). A single value also works.
OHLCV_TIMEFRAMES = [
    tf.strip().upper()
    for tf in os.getenv("NEXUS_OHLCV_TIMEFRAME", "M15").split(",")
    if tf.strip()
] or ["M15"]
OHLCV_BAR_COUNT = int(os.getenv("NEXUS_OHLCV_BAR_COUNT", "300"))

import json as _json

async def _ohlcv_publisher() -> None:
    """Fetch full OHLCV history from MT5, cache in Redis, publish stream event.

    nexus-features reads the cached bars to compute indicators.
    """
    await asyncio.sleep(3)
    consecutive_failures = 0

    while True:
        for symbol in STREAM_SYMBOLS:
            for tf in OHLCV_TIMEFRAMES:
                try:
                    bars = await mt5.get_ohlcv(symbol, tf, OHLCV_BAR_COUNT)
                    if not bars:
                        await log.awarning("ohlcv.no_bars", symbol=symbol, tf=tf)
                        continue

                    bars_json = [
                        {
                            "timestamp": b.timestamp.isoformat(),
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                        }
                        for b in bars
                    ]

                    cache_key = f"nexus:ohlcv:{symbol}:{tf}"
                    await redis_client.r.set(cache_key, _json.dumps(bars_json), ex=3600)

                    last_bar = bars[-1]
                    await redis_client.publish_event(
                        RedisStream.OHLCV_STREAM,
                        OHLCVEvent(
                            source="nexus-data",
                            symbol=last_bar.symbol,
                            timeframe=last_bar.timeframe,
                            open=last_bar.open,
                            high=last_bar.high,
                            low=last_bar.low,
                            close=last_bar.close,
                            volume=last_bar.volume,
                        ),
                    )
                    consecutive_failures = 0
                    await log.ainfo(
                        "ohlcv.published",
                        symbol=symbol,
                        tf=tf,
                        bars=len(bars),
                        close=round(last_bar.close, 2),
                    )
                except Exception:
                    consecutive_failures += 1
                    await log.aexception(
                        "ohlcv_publisher_error",
                        symbol=symbol,
                        tf=tf,
                        failures=consecutive_failures,
                    )
                    if consecutive_failures >= 3 and mt5.connected:
                        await log.awarning("ohlcv.reconnecting_mt5")
                        try:
                            await mt5.disconnect()
                            await asyncio.sleep(2)
                            await mt5.connect(
                                login=MT5_LOGIN,
                                password=MT5_PASSWORD,
                                server=MT5_SERVER,
                                path=MT5_PATH,
                            )
                            consecutive_failures = 0
                        except Exception:
                            await log.aexception("ohlcv.reconnect_failed")

        await asyncio.sleep(OHLCV_POLL_SEC)


async def _synthetic_feed_loop() -> None:
    """Offline-dev feed — emulate MT5 ticks + OHLCV when no terminal exists.

    Activated only when NEXUS_DATA_SYNTHETIC_FALLBACK=1 and the broker feed
    cannot connect (e.g. a Linux box without a Windows MT5 terminal).

    Maintains a stateful random-walk price series per symbol (mean-reverting
    around the symbol's base price). Ticks walk the series continuously and
    each OHLCV poll folds the latest steps into a new bar, so features, labels
    and model votes see a coherent, evolving market instead of a static sine.
    """
    import random
    import time as _time
    from collections import deque

    await log.awarning("synthetic_feed.started", symbols=STREAM_SYMBOLS)

    STEP_SIGMA = 0.0006          # per-step volatility of the walk
    MEAN_REVERT = 0.0015         # pull back toward the base price
    BAR_TICKS = 4                # synthetic bars advance every N polls

    state: dict[str, dict[str, Any]] = {}
    for s in STREAM_SYMBOLS:
        seed_hist = _synthetic_ohlcv(s, "M5", OHLCV_BAR_COUNT)
        series = deque(
            [b.close for b in seed_hist], maxlen=OHLCV_BAR_COUNT
        )
        state[s] = {
            "price": series[-1],
            "series": series,
            "bar": {"open": series[-1], "high": series[-1], "low": series[-1]},
            "bar_step": 0,
            "volume": 0.0,
        }

    last_ohlcv_ts = 0.0

    def _advance(symbol: str) -> None:
        st = state[symbol]
        base = _base_price(symbol)
        ret = random.gauss(0.0, STEP_SIGMA)
        ret += (base - st["price"]) / base * MEAN_REVERT
        st["price"] = max(base * 0.5, st["price"] * (1.0 + ret))
        st["series"].append(st["price"])
        bar = st["bar"]
        bar["high"] = max(bar["high"], st["price"])
        bar["low"] = min(bar["low"], st["price"])
        st["volume"] += abs(random.gauss(120.0, 40.0))

    def _roll_bar(symbol: str, now: datetime) -> OHLCV:
        st = state[symbol]
        bar = st["bar"]
        out = OHLCV(
            symbol=symbol,
            timeframe="M5",
            open=bar["open"],
            high=bar["high"],
            low=bar["low"],
            close=st["price"],
            volume=st["volume"] or 100.0,
            timestamp=now.replace(second=0, microsecond=0),
        )
        st["bar"] = {"open": st["price"], "high": st["price"], "low": st["price"]}
        st["volume"] = 0.0
        return out

    while True:
        loop_start = _time.monotonic()
        now = datetime.now(timezone.utc)

        # 1) Ticks — random walk, fanned out via the same _on_tick path
        for symbol in STREAM_SYMBOLS:
            try:
                _advance(symbol)
                st = state[symbol]
                spread = 0.25 if symbol.startswith("XAU") else st["price"] * 0.0002
                bid = st["price"]
                await _on_tick(Tick(symbol=symbol, bid=bid, ask=bid + spread, timestamp=now))
            except Exception:
                await log.aexception("synthetic_tick_error", symbol=symbol)

        # 2) OHLCV — publish the evolved series (walk history + current bar)
        if now.timestamp() - last_ohlcv_ts >= OHLCV_POLL_SEC:
            last_ohlcv_ts = now.timestamp()
            for symbol in STREAM_SYMBOLS:
                try:
                    st = state[symbol]
                    st["bar_step"] += 1
                    if st["bar_step"] >= BAR_TICKS:
                        st["bar_step"] = 0
                        _roll_bar_hist = _roll_bar(symbol, now)
                    bars: list[OHLCV] = []
                    series = list(st["series"])
                    n = len(series)
                    for i in range(1, n):
                        prev_c = series[i - 1]
                        close = series[i]
                        hi = max(prev_c, close)
                        lo = min(prev_c, close)
                        bars.append(OHLCV(
                            symbol=symbol,
                            timeframe="M5",
                            open=prev_c,
                            high=hi * (1 + 0.0003),
                            low=lo * (1 - 0.0003),
                            close=close,
                            volume=100.0 + (i * 37) % 900,
                            timestamp=now - timedelta(minutes=5 * (n - i)),
                        ))
                    if st["bar_step"] != 0:
                        cur = st["bar"]
                        bars.append(OHLCV(
                            symbol=symbol,
                            timeframe="M5",
                            open=cur["open"],
                            high=cur["high"],
                            low=cur["low"],
                            close=st["price"],
                            volume=st["volume"] or 100.0,
                            timestamp=now.replace(second=0, microsecond=0),
                        ))
                    if not bars:
                        continue
                    bars_json = [
                        {
                            "timestamp": b.timestamp.isoformat(),
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                        }
                        for b in bars
                    ]
                    cache_key = f"nexus:ohlcv:{symbol}:M5"
                    await redis_client.r.set(cache_key, _json.dumps(bars_json), ex=3600)
                    last_bar = bars[-1]
                    await redis_client.publish_event(
                        RedisStream.OHLCV_STREAM,
                        OHLCVEvent(
                            source="nexus-data",
                            symbol=last_bar.symbol,
                            timeframe=last_bar.timeframe,
                            open=last_bar.open,
                            high=last_bar.high,
                            low=last_bar.low,
                            close=last_bar.close,
                            volume=last_bar.volume,
                        ),
                    )
                except Exception:
                    await log.aexception("synthetic_ohlcv_error", symbol=symbol)

        elapsed = _time.monotonic() - loop_start
        await asyncio.sleep(max(0.2, 1.2 - elapsed))


# ── Yahoo Finance live feed (free real prices) ───────────────────────────────

def _df_to_bars(symbol: str, df: Any) -> list[OHLCV]:
    """Normalize a yfinance DataFrame into OHLCV M5 bars (UTC timestamps)."""
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    lower = {str(c).lower(): c for c in df.columns}

    def _col(name: str) -> Any:
        return lower.get(name)

    c_o, c_h, c_l, c_c, c_v = (
        _col("open"), _col("high"), _col("low"), _col("close"), _col("volume"),
    )
    if c_c is None:
        return []

    bars: list[OHLCV] = []
    for idx, row in df.iterrows():
        try:
            ts = idx.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            def _f(col: Any, default: float) -> float:
                if col is None:
                    return default
                val = row[col]
                if pd.isna(val):
                    return default
                return float(val)

            close = _f(c_c, 0.0)
            if close <= 0.0:
                continue
            bars.append(OHLCV(
                symbol=symbol,
                timeframe="M5",
                open=_f(c_o, close),
                high=_f(c_h, close),
                low=_f(c_l, close),
                close=close,
                volume=_f(c_v, 0.0),
                timestamp=ts,
            ))
        except Exception:
            continue
    return bars


async def _publish_bars(symbol: str, bars: list[OHLCV]) -> None:
    """Publish bars through the SAME path the broker/synthetic feeds use:
    Redis cache (REST reads) + OHLCV stream (features/ML) + DuckDB (history)."""
    import json as _json

    if not bars:
        return
    bars_json = [
        {
            "timestamp": b.timestamp.isoformat(),
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    # Merge with the existing cache so incremental updates (1 bar) extend
    # the rolling window instead of shrinking it to a single candle.
    _key = f"nexus:ohlcv:{symbol}:M5"
    merged: list[dict] = []
    _raw = await redis_client.r.get(_key)
    if _raw:
        try:
            _old = _json.loads(_raw)
            if isinstance(_old, list):
                merged = [m for m in _old if isinstance(m, dict)]
        except Exception:
            merged = []
    _known = {m.get("timestamp") for m in merged}
    merged.extend(bj for bj in bars_json if bj["timestamp"] not in _known)
    merged.sort(key=lambda m: m.get("timestamp", ""))
    merged = merged[-OHLCV_BAR_COUNT:]
    await redis_client.r.set(
        _key, _json.dumps(merged), ex=7200
    )
    last = bars[-1]
    await redis_client.publish_event(
        RedisStream.OHLCV_STREAM,
        OHLCVEvent(
            source="nexus-data",
            symbol=last.symbol,
            timeframe=last.timeframe,
            open=last.open,
            high=last.high,
            low=last.low,
            close=last.close,
            volume=last.volume,
        ),
    )
    if bars and all(b.source_id for b in bars):
        # Source-aware bridge ingestion already committed these bars before
        # publishing; do not create a second physical copy here.
        pass
    elif len(bars) >= 50:
        # Seed-like publish (full window from yahoo seed or the MT5 bridge):
        # bulk insert + dedupe so REST/chart history is immediately rich.
        try:
            await data_store.insert_batch(bars)
            removed = await data_store.dedupe_ohlcv()
            await log.ainfo(
                "ohlcv.history_persisted", symbol=bars[0].symbol,
                rows=len(bars), dupes_removed=removed,
            )
        except Exception:
            await log.aexception("ohlcv_bulk_persist_failed")
    else:
        for b in bars[-10:]:  # persist tail only — REST history comes from DuckDB
            try:
                await data_store.insert_ohlcv(b)
            except Exception:
                pass


async def _yahoo_feed_loop() -> None:
    """Live market data from Yahoo Finance — free, real prices.

    Polls 5-minute bars via yfinance and feeds the exact same pipeline as
    the broker/synthetic feeds (ticks via _on_tick, bars via the
    nexus:ohlcv cache + OHLCV stream + DuckDB), so features, ML, agents
    and the dashboard see REAL market prices without any code changes
    downstream.

    Honest caveats (by design, not bugs):
      - Yahoo FX/futures quotes are indicative and delayed ~1-15 min.
      - XAUUSD uses COMEX gold futures (GC=F): real gold prices with a
        small futures basis vs broker spot.
      - No tick-level bid/ask — spread is synthesized from the mid.
    Good for paper trading and pipeline validation; live execution still
    wants a broker-grade feed (MT5).
    """
    import time as _time

    from .yfinance_connector import YFinanceConnector

    yh = YFinanceConnector()
    await log.awarning(
        "yahoo_feed.started",
        symbols=STREAM_SYMBOLS,
        yahoo_map={s: _yahoo_symbol(s) for s in STREAM_SYMBOLS},
        poll_sec=YAHOO_POLL_SEC,
    )

    state: dict[str, dict[str, Any]] = {
        s: {"last_bar_ts": None, "last_price": None, "seeded": False}
        for s in STREAM_SYMBOLS
    }

    while True:
        loop_start = _time.monotonic()
        for symbol in STREAM_SYMBOLS:
            st = state[symbol]
            try:
                # Seed deep history once; afterwards poll just today.
                if not st["seeded"]:
                    df = await yh.get_historical(
                        _yahoo_symbol(symbol), period="5d", interval="5m"
                    )
                else:
                    df = await yh.get_historical(
                        _yahoo_symbol(symbol), period="1d", interval="5m"
                    )
                bars = _df_to_bars(symbol, df)
                if not bars:
                    continue

                prev_ts = st["last_bar_ts"]
                new_bars = [
                    b for b in bars
                    if prev_ts is None or b.timestamp > prev_ts
                ]

                if not st["seeded"]:
                    # First pass: publish the full recent window so features,
                    # ML and the chart REST immediately have real history.
                    # _publish_bars bulk-persists windows >= 50 bars to DuckDB.
                    await _publish_bars(symbol, bars[-OHLCV_BAR_COUNT:])
                    st["seeded"] = True
                    st["last_bar_ts"] = bars[-1].timestamp
                    st["last_price"] = bars[-1].close
                    await log.ainfo(
                        "yahoo_feed.seeded", symbol=symbol, bars=len(bars),
                        last_close=bars[-1].close,
                    )
                elif new_bars:
                    await _publish_bars(symbol, new_bars[-OHLCV_BAR_COUNT:])
                    st["last_bar_ts"] = new_bars[-1].timestamp

                # Emit a tick from the latest close (real price, synthesized spread)
                price = float(bars[-1].close)
                if price > 0 and price != st["last_price"]:
                    spread = (
                        max(0.25, price * 0.0002)
                        if symbol.startswith("XAU")
                        else price * 0.0002
                    )
                    await _on_tick(Tick(
                        symbol=symbol,
                        bid=price,
                        ask=price + spread,
                        timestamp=datetime.now(timezone.utc),
                    ))
                    st["last_price"] = price
            except Exception:
                await log.aexception("yahoo_poll_error", symbol=symbol)

        elapsed = _time.monotonic() - loop_start
        await asyncio.sleep(max(2.0, YAHOO_POLL_SEC - elapsed))


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await log.ainfo("startup.begin")

    # 1. Redis
    await redis_client.connect()
    await log.ainfo("startup.redis_connected")

    # 2. DuckDB (must finish before yield — run.py gates other services on this)
    try:
        await data_store.init_tables()
    except Exception:
        await log.aexception("startup.duckdb_failed")
        raise
    await log.ainfo("startup.duckdb_ready")

    # 3. Broker feeds in background so /health responds while MT5 connects
    async def _start_broker_feeds() -> None:
        # External MT5 bridge mode: the bridge (Windows) posts ticks/bars to
        # /api/data/ingest/* — no internal loop is started here.
        if DATA_SOURCE == "bridge":
            await log.ainfo(
                "startup.bridge_mode", symbols=STREAM_SYMBOLS,
                hint="waiting for external MT5 bridge on /api/data/ingest/*",
            )
            return

        # Yahoo Finance source — free real prices, no terminal required.
        if DATA_SOURCE == "yahoo":
            task = asyncio.create_task(_yahoo_feed_loop())
            _streaming_tasks.append(task)
            await log.ainfo(
                "startup.yahoo_streaming", symbols=STREAM_SYMBOLS
            )
            return

        if DEFAULT_BROKER == "mt5" and MT5_LOGIN:
            try:
                await mt5.connect(
                    login=MT5_LOGIN,
                    password=MT5_PASSWORD,
                    server=MT5_SERVER,
                    path=MT5_PATH,
                )
                task = asyncio.create_task(
                    mt5.stream_ticks(STREAM_SYMBOLS, _on_tick)
                )
                _streaming_tasks.append(task)

                ohlcv_task = asyncio.create_task(_ohlcv_publisher())
                _streaming_tasks.append(ohlcv_task)

                await log.ainfo("startup.mt5_streaming", symbols=STREAM_SYMBOLS)
            except Exception:
                await log.aexception("startup.mt5_failed")
                if SYNTHETIC_FALLBACK:
                    _task = asyncio.create_task(_synthetic_feed_loop())
                    _streaming_tasks.append(_task)

        if IBKR_HOST and os.getenv("ENABLE_IBKR", ""):
            try:
                await ibkr.connect(
                    host=IBKR_HOST,
                    port=IBKR_PORT,
                    client_id=IBKR_CLIENT_ID,
                )
                await log.ainfo("startup.ibkr_connected")
            except Exception:
                await log.aexception("startup.ibkr_failed")

        if CCXT_API_KEY and os.getenv("ENABLE_CCXT", ""):
            try:
                await ccxt_conn.connect(
                    exchange_name=CCXT_EXCHANGE,
                    api_key=CCXT_API_KEY,
                    secret=CCXT_SECRET,
                )
                await log.ainfo("startup.ccxt_connected")
            except Exception:
                await log.aexception("startup.ccxt_failed")

    trade_task = asyncio.create_task(_trade_close_consumer())
    _streaming_tasks.append(trade_task)
    feed_task = asyncio.create_task(_start_broker_feeds())
    _streaming_tasks.append(feed_task)
    await log.ainfo("startup.trade_consumer_started")
    await log.ainfo("startup.complete")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    await log.ainfo("shutdown.begin")

    for t in _streaming_tasks:
        t.cancel()
    if _streaming_tasks:
        await asyncio.gather(*_streaming_tasks, return_exceptions=True)
    _streaming_tasks.clear()

    await mt5.disconnect()
    await ibkr.disconnect()
    await ccxt_conn.disconnect()
    data_store.close()
    await redis_client.disconnect()

    await log.ainfo("shutdown.complete")


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus Data Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check() -> dict[str, Any]:
    redis_ok = await redis_client.health_check()
    mt5_ok = mt5.connected
    data_mode = "REAL_MT5" if mt5_ok and not SYNTHETIC_FALLBACK else (
        "SYNTHETIC_ALLOWED" if SYNTHETIC_FALLBACK else "REAL_MT5_REQUIRED"
    )
    duckdb_ok = data_store.is_open
    # Startup gate: DuckDB writer must be up; MT5 may still be connecting.
    if redis_ok and duckdb_ok and mt5_ok:
        status = "healthy"
    elif redis_ok and duckdb_ok:
        status = "degraded"
    else:
        status = "unhealthy"
    return {
        "service": "nexus-data",
        "status": status,
        "ready": redis_ok and duckdb_ok,
        "data_mode": data_mode,
        "synthetic_fallback": SYNTHETIC_FALLBACK,
        "redis": redis_ok,
        "duckdb": data_store.is_open,
        "mt5": mt5_ok,
        "ibkr": ibkr.connected,
        "ccxt": ccxt_conn.connected,
    }


# ── Tick endpoint ────────────────────────────────────────────────────────────

@app.get("/api/data/ticks/{symbol}", response_model=list[Tick])
async def get_ticks(
    symbol: str,
    count: int = Query(default=50, ge=1, le=1000),
    source: str = Query(default="cache", pattern="^(cache|db)$"),
) -> list[Tick]:
    """Return the most recent ticks for *symbol*."""
    symbol = symbol.upper().replace("/", "")
    if source == "cache":
        ticks = await tick_cache.get_tick_history(symbol, count)
        return ticks or []

    rows = await data_store.query_latest_ticks(symbol, count)
    if rows:
        return rows

    if DEFAULT_BROKER == "mt5" and mt5.connected:
        try:
            live = await mt5.get_tick(symbol)
            return [live]
        except Exception:
            await log.aexception("ticks_mt5_fallback_failed", symbol=symbol)

    if SYNTHETIC_FALLBACK:
        await log.awarning("ticks.synthetic_fallback", symbol=symbol)
        return [_synthetic_tick(symbol)]

    raise HTTPException(404, f"No ticks found for {symbol}")


# ── Order flow (derived from M1 bars + latest tick) ──────────────────────────

@app.get("/api/flow/{symbol}")
@app.get("/api/data/flow/{symbol}")
async def get_order_flow(symbol: str, bars: int = Query(default=20, ge=5, le=100)) -> dict[str, Any]:
    """Estimate bid/ask pressure from recent M1 candle direction and volume."""
    symbol = symbol.upper().replace("/", "")
    bars_data = await data_store.query_ohlcv(symbol, "M1", limit=bars)
    if not bars_data:
        try:
            bars_data = await mt5.get_ohlcv(symbol, "M1", bars)
        except Exception:
            bars_data = []

    bid_volume = 0.0
    ask_volume = 0.0
    spreads: list[float] = []

    for bar in bars_data:
        vol = float(getattr(bar, "volume", 0) or (bar.get("volume", 0) if isinstance(bar, dict) else 0))
        o = float(getattr(bar, "open", 0) or (bar.get("open", 0) if isinstance(bar, dict) else 0))
        c = float(getattr(bar, "close", 0) or (bar.get("close", 0) if isinstance(bar, dict) else 0))
        if vol <= 0:
            continue
        if c >= o:
            bid_volume += vol
        else:
            ask_volume += vol

    ticks = await tick_cache.get_tick_history(symbol, 5)
    if not ticks:
        rows = await data_store.query_latest_ticks(symbol, 5)
        ticks = rows or []
    for t in ticks:
        sp = float(getattr(t, "spread", 0) or (t.get("spread", 0) if isinstance(t, dict) else 0))
        if sp > 0:
            spreads.append(sp)

    spread_current = spreads[-1] if spreads else 0.0
    spread_avg = sum(spreads) / len(spreads) if spreads else spread_current or 1.0
    total = bid_volume + ask_volume
    delta = bid_volume - ask_volume
    imbalance = delta / total if total else 0.0

    absorption = "none"
    if total > 0 and abs(imbalance) < 0.1:
        absorption = "balanced"
    elif imbalance > 0.35:
        absorption = "buy_absorption"
    elif imbalance < -0.35:
        absorption = "sell_absorption"

    return {
        "symbol": symbol,
        "bid_volume": round(bid_volume, 2),
        "ask_volume": round(ask_volume, 2),
        "delta": round(delta, 2),
        "absorption": absorption,
        "spread": round(spread_current, 5),
        "spread_avg": round(spread_avg, 5),
        "imbalance": round(imbalance, 4),
        "large_orders": [],
        "iceberg_detected": False,
        "bars_analyzed": len(bars_data),
    }


# ── OHLCV endpoint ───────────────────────────────────────────────────────────

@app.get("/api/data/ohlcv/{symbol}/{timeframe}", response_model=list[OHLCV])
async def get_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=500, ge=1, le=5000),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> list[OHLCV]:
    """Return OHLCV bars for *symbol* / *timeframe*."""
    symbol = symbol.upper().replace("/", "")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            400,
            f"Unsupported timeframe '{timeframe}'. Use one of {SUPPORTED_TIMEFRAMES}",
        )
    rows = await data_store.query_ohlcv(
        symbol=symbol, timeframe=timeframe, start=start, end=end, limit=limit,
    )
    if rows:
        return rows

    # DuckDB ``ohlcv`` is not filled from tick ingest — pull live bars from MT5 when connected.
    if DEFAULT_BROKER == "mt5" and mt5.connected and not start and not end:
        try:
            return await mt5.get_ohlcv(symbol, timeframe, limit)
        except Exception:
            await log.aexception("ohlcv_mt5_fallback_failed", symbol=symbol, tf=timeframe)

    if SYNTHETIC_FALLBACK and not start and not end:
        await log.awarning("ohlcv.synthetic_fallback", symbol=symbol, tf=timeframe)
        return _synthetic_ohlcv(symbol, timeframe, limit)

    raise HTTPException(404, f"No OHLCV data for {symbol}/{timeframe}")


# ── External bridge ingest (MT5 bridge on Windows) ──────────────────────────

class _BridgeTick(BaseModel):
    symbol: str
    bid: float
    ask: float
    timestamp: datetime | None = None


class _BridgeBar(BaseModel):
    symbol: str
    timeframe: str = "M5"
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timestamp: datetime | None = None


def _bridge_ok(request: Request) -> None:
    if BRIDGE_TOKEN and request.headers.get("x-bridge-token") != BRIDGE_TOKEN:
        raise HTTPException(401, "invalid bridge token")


def _internal_service_ok(request: Request) -> None:
    if len(INTERNAL_SERVICE_TOKEN) < 32:
        raise HTTPException(503, "internal source-revision ingestion is not configured")
    supplied = request.headers.get("x-nexus-service-token", "")
    if not supplied or not hmac.compare_digest(supplied, INTERNAL_SERVICE_TOKEN):
        raise HTTPException(401, "invalid internal service token")


@app.post("/api/data/ingest/ticks")
async def bridge_ingest_ticks(request: Request, body: dict[str, Any]):
    """Live ticks from the external MT5 bridge → exact same pipeline as
    internal feeds (tick cache + ticks stream + DuckDB)."""
    _bridge_ok(request)
    received = body.get("ticks") or []
    batch_id = body.get("batch_id")
    source = body.get("source")
    if batch_id and isinstance(source, dict):
        try:
            chunk_result = await data_store.persist_tick_batch_chunk(
                source=source,
                contract_snapshot=body.get("contract_snapshot"),
                batch_id=str(batch_id),
                window_start_ms=int(body["window_start_ms"]),
                window_end_ms=int(body["window_end_ms"]),
                chunk_index=int(body["chunk_index"]),
                chunk_count=int(body["chunk_count"]),
                ticks=received,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, f"invalid tick batch metadata: {exc}") from exc
        except Exception as exc:
            await log.aexception("bridge_tick_batch_persist_failed")
            raise HTTPException(500, "tick batch persistence failed; do not advance watermark") from exc

        # Fan out only after the durable source-table transaction commits.
        # Preserve source identity in Redis event metadata and avoid writing
        # the same tick a second time through _on_tick().
        for t in received:
            try:
                ts = datetime.fromisoformat(t["timestamp"])
                tick = Tick(
                    symbol=str(source["logical_symbol"]).upper(), bid=float(t["bid"]),
                    ask=float(t["ask"]), timestamp=ts, source_id=str(source["source_id"]),
                    provider=source.get("provider"), broker=source.get("broker"),
                    server=source.get("server"), logical_symbol=source.get("logical_symbol"),
                    raw_symbol=source.get("raw_symbol"),
                    contract_snapshot_id=(body.get("contract_snapshot") or {}).get("snapshot_id"),
                    time_msc=int(t["time_msc"]), last=float(t.get("last") or 0),
                    volume=float(t.get("volume") or 0), volume_real=float(t.get("volume_real") or 0),
                    flags=int(t.get("flags") or 0),
                )
                await asyncio.gather(
                    tick_cache.cache_tick(tick),
                    redis_client.publish_event(
                        RedisStream.TICK_STREAM,
                        TickEvent(source="mt5-bridge", symbol=tick.symbol, bid=tick.bid,
                                  ask=tick.ask, spread=tick.spread),
                    ),
                )
            except Exception:
                await log.aexception("bridge_tick_batch_fanout_failed")
        return chunk_result

    accepted = 0
    for t in received[-100:]:
        try:
            ts = t.get("timestamp")
            await _on_tick(Tick(
                symbol=str(t.get("symbol", "")).upper(),
                bid=float(t["bid"]),
                ask=float(t["ask"]),
                timestamp=(
                    datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
                ),
            ))
            accepted += 1
        except Exception:
            await log.aexception("bridge_tick_rejected")
    if accepted:
        await log.ainfo("bridge.ticks_ingested", accepted=accepted)
    return {"accepted": accepted, "received": len(received)}


@app.post("/api/data/ingest/bars")
async def bridge_ingest_bars(request: Request, body: dict[str, Any]):
    """OHLCV bars from the external MT5 bridge → _publish_bars
    (Redis cache merge + OHLCV stream + DuckDB) — identical to internal feeds."""
    _bridge_ok(request)
    received = body.get("bars") or []
    source = body.get("source")
    contract_snapshot = body.get("contract_snapshot")
    by_symbol: dict[str, list[OHLCV]] = {}
    for b in received:
        try:
            ts = b.get("timestamp")
            bar = OHLCV(
                symbol=str((source or {}).get("logical_symbol") or b.get("symbol") or body.get("symbol", "")).upper(),
                timeframe=str(b.get("timeframe", "M5")),
                open=float(b["open"]),
                high=float(b["high"]),
                low=float(b["low"]),
                close=float(b["close"]),
                volume=float(b.get("volume") or 0.0),
                timestamp=(
                    datetime.fromisoformat(ts or b.get("time")) if (ts or b.get("time")) else datetime.now(timezone.utc)
                ),
                source_id=(source or {}).get("source_id"),
                provider=(source or {}).get("provider"),
                broker=(source or {}).get("broker"),
                server=(source or {}).get("server"),
                logical_symbol=(source or {}).get("logical_symbol"),
                raw_symbol=(source or {}).get("raw_symbol"),
                contract_snapshot_id=(contract_snapshot or {}).get("snapshot_id"),
                real_volume=float(b.get("real_volume") or 0),
            )
            by_symbol.setdefault(bar.symbol, []).append(bar)
        except Exception:
            await log.aexception("bridge_bar_rejected")
    accepted = 0
    for sym, bars in by_symbol.items():
        bars.sort(key=lambda x: x.timestamp)
        if isinstance(source, dict):
            try:
                await data_store.persist_source_bars(
                    source=source, contract_snapshot=contract_snapshot,
                    bars=[{
                        "timeframe": bar.timeframe, "timestamp": bar.timestamp.isoformat(),
                        "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
                        "volume": bar.volume, "real_volume": bar.real_volume,
                    } for bar in bars],
                )
            except Exception as exc:
                await log.aexception("bridge_source_bars_persist_failed")
                raise HTTPException(500, "source bars persistence failed") from exc
        await _publish_bars(sym, bars)
        accepted += len(bars)
    if accepted:
        await log.ainfo("bridge.bars_ingested", accepted=accepted)
    return {"accepted": accepted, "received": len(received)}


@app.post("/api/data/ingest/calendar")
async def bridge_ingest_calendar(request: Request, body: dict[str, Any]):
    """Economic-calendar events from the MT5 bridge (via a companion EA that
    dumps MQL5 CalendarValueHistory to JSON — the Python API cannot read the
    calendar directly). Stored for the News Sentinel / dashboard consumption."""
    _bridge_ok(request)
    received = body.get("events") or []

    def _clean_metric(v: Any) -> Any:
        """Guard against unscaled / sentinel values leaking into ML features.

        MQL5 stores calendar values ×10^6 and uses LONG_MIN for "no value";
        a malformed producer shows up as astronomically large numbers
        (e.g. -9.2e17). Anything beyond ±1e12 after stripping unit suffixes
        is treated as absent."""
        if v is None:
            return None
        s = str(v).strip()
        try:
            x = float(s.rstrip("%KMBT"))
            if abs(x) > 1e12:
                return None
        except ValueError:
            pass
        return s

    cleaned: list[dict] = []
    available_at = datetime.now(timezone.utc).isoformat()
    for e in received[:200]:
        try:
            event = {
                "event_id": str(e.get("event_id", ""))[:64],
                "name": str(e.get("name", ""))[:160],
                "country": str(e.get("country", ""))[:8],
                "currency": str(e.get("currency", ""))[:8],
                "importance": str(e.get("importance", ""))[:16],
                "time": str(e.get("time", ""))[:40],
                "forecast": _clean_metric(e.get("forecast")),
                "previous": _clean_metric(e.get("previous")),
                "actual": _clean_metric(e.get("actual")),
                "impact": str(e.get("impact", ""))[:32],
                "available_at": available_at,
            }
            import hashlib as _hashlib
            if not event["event_id"]:
                identity = f"{event['currency']}|{event['name']}|{event['time']}"
                event["event_id"] = _hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            revision_content = {k: v for k, v in event.items() if k != "available_at"}
            revision_payload = _json.dumps(revision_content, sort_keys=True, separators=(",", ":"))
            event["revision_id"] = _hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()[:32]
            event["source"] = "mt5_calendar"
            cleaned.append(event)
        except Exception:
            continue
    if cleaned:
        try:
            await data_store.persist_calendar_revisions(cleaned)
        except Exception as exc:
            await log.aexception("calendar_revision_persist_failed")
            raise HTTPException(500, "calendar revision history could not be persisted") from exc
        import json as _json
        await redis_client.r.set(
            "nexus:calendar:mt5", _json.dumps(cleaned), ex=86400
        )
        await log.ainfo("bridge.calendar_ingested", accepted=len(cleaned))
    return {"accepted": len(cleaned), "received": len(received)}


@app.post("/api/data/ingest/source-revisions")
async def ingest_source_revisions(request: Request, body: dict[str, Any]):
    """Internal append-only point-in-time archive; DuckDB remains data-owned."""
    _internal_service_ok(request)
    caller = str(body.get("caller_service") or "").strip()
    if caller not in _REVISION_INGEST_CALLERS:
        raise HTTPException(403, "caller is not allowed to ingest source revisions")
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise HTTPException(422, "records must be a non-empty list")
    if len(records) > 500:
        raise HTTPException(413, "at most 500 source revisions may be submitted per batch")
    try:
        accepted = await data_store.persist_source_revisions(records, caller_service=caller)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        await log.aexception("source_revisions_persist_failed", caller_service=caller)
        raise HTTPException(500, "source revisions could not be persisted") from exc
    return {"accepted": accepted, "received": len(records)}


# ── Subscribe endpoint ───────────────────────────────────────────────────────

@app.get("/api/data/performance")
async def get_performance() -> dict:
    return await data_store.get_performance_metrics()


@app.get("/api/data/performance/equity-curve")
async def get_equity_curve(limit: int = Query(200, ge=1, le=2000)) -> list:
    return await data_store.get_pnl_curve(limit=limit)


@app.get("/api/data/performance/daily")
async def get_daily_pnl(since: str | None = Query(None)) -> list:
    return await data_store.get_daily_pnl(since=since)


@app.get("/api/data/performance/by-session")
async def get_perf_by_session() -> list:
    return await data_store.get_grouped_performance("session")


@app.get("/api/data/performance/by-symbol")
async def get_perf_by_symbol() -> list:
    return await data_store.get_grouped_performance("symbol")


@app.get("/api/data/trades")
async def get_trades_history(
    symbol: str | None = Query(None),
    session: str | None = Query(None),
    since: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
) -> dict:
    """Paginated trade history from DuckDB — served by the owner of the write lock."""
    return await data_store.query_trades(
        symbol=symbol,
        session=session,
        since=since,
        page=page,
        page_size=page_size,
    )


class SubscribeRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    broker: str = Field(default="mt5", pattern="^(mt5|ibkr|ccxt)$")


@app.post("/api/data/subscribe")
async def subscribe(req: SubscribeRequest) -> dict[str, Any]:
    """Start streaming ticks for additional symbols at runtime."""
    broker_map = {"mt5": mt5, "ibkr": ibkr, "ccxt": ccxt_conn}
    connector = broker_map.get(req.broker)
    if connector is None or not connector.connected:
        raise HTTPException(
            503, f"Broker '{req.broker}' is not connected",
        )

    task = asyncio.create_task(
        connector.stream_ticks(req.symbols, _on_tick),
    )
    _streaming_tasks.append(task)

    await log.ainfo(
        "subscribe.started", broker=req.broker, symbols=req.symbols,
    )
    return {"status": "subscribed", "symbols": req.symbols, "broker": req.broker}
