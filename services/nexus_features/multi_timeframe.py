"""
Multi-timeframe feature aggregation.

Pulls cached OHLCV data from Redis for each requested timeframe,
calculates indicators, and merges the results into a single dict
keyed by ``{timeframe}_{indicator}``.

The MTF trend-alignment score collapses EMA/RSI/MACD across timeframes
into a single integer from **-4** (strongly bearish) to **+4**
(strongly bullish).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import redis.asyncio as aioredis

from shared.constants import (
    CACHE_FEATURE_PREFIX,
    CACHE_OHLCV_PREFIX,
    SUPPORTED_TIMEFRAMES,
)

from .indicators import calculate_all

_TIMEFRAME_SECONDS = {
    "M1": 60, "M2": 120, "M3": 180, "M4": 240, "M5": 300,
    "M6": 360, "M10": 600, "M12": 720, "M15": 900, "M20": 1200,
    "M30": 1800, "H1": 3600, "H2": 7200, "H3": 10800,
    "H4": 14400, "H6": 21600, "H8": 28800, "H12": 43200,
    "D1": 86400, "W1": 604800,
}


# ── Public API ───────────────────────────────────────────────────────────────

async def aggregate_features(
    symbol: str,
    timeframes: list[str] | None = None,
    *,
    redis: aioredis.Redis,
    as_of: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Return ``{timeframe: {indicator: value, …}, …}`` for every requested tf.
    """
    if timeframes is None:
        timeframes = ["M1", "M5", "M15", "H1", "H4"]

    decision_time = pd.Timestamp(as_of or datetime.now(timezone.utc))
    if decision_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    decision_time = decision_time.tz_convert("UTC")

    result: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        tf = str(tf).upper()
        duration = _TIMEFRAME_SECONDS.get(tf)
        if duration is None:
            continue
        key = f"{CACHE_OHLCV_PREFIX}{symbol}:{tf}"
        raw = await redis.get(key)
        if raw is None:
            continue
        data = json.loads(raw)
        if not data or not isinstance(data, list):
            continue
        df = pd.DataFrame(data)
        if "timestamp" not in df.columns:
            # Without market-time evidence we cannot establish a closed bar.
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df.dropna(subset=["timestamp"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
        df = df.loc[df["timestamp"] + pd.to_timedelta(duration, unit="s") <= decision_time]
        if df.empty:
            continue
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

        df = calculate_all(df)
        last = df.iloc[-1]
        features: dict[str, Any] = {}
        for col in df.columns:
            if col in ("open", "high", "low", "close", "volume", "timestamp", "symbol", "timeframe"):
                continue
            val = last[col]
            if isinstance(val, (int, float, np.integer, np.floating)) and np.isfinite(val):
                features[col] = round(float(val), 6)
        features["_source_bar_timestamp"] = pd.Timestamp(last["timestamp"]).isoformat()
        features["_available_at"] = (pd.Timestamp(last["timestamp"]) + pd.to_timedelta(duration, unit="s")).isoformat()
        result[tf] = features

    return result


def calculate_mtf_trend_alignment(
    features_dict: dict[str, dict[str, float]],
) -> int:
    """
    Score from **-4** (all bearish) to **+4** (all bullish).

    For each timeframe present, +1 if bullish signal, -1 if bearish:
    * EMA 9 > EMA 21 → bullish
    * RSI > 50 → bullish
    * MACD histogram > 0 → bullish
    * Close > EMA 200 → bullish (only on higher TFs H1+)
    """
    score = 0
    tf_weight = {
        "M1": 0, "M5": 0, "M15": 1, "M30": 1, "H1": 1, "H4": 1, "D1": 1,
    }
    for tf, feats in features_dict.items():
        w = tf_weight.get(tf, 1)
        if not w:
            continue
        ema9 = feats.get("ema_9")
        ema21 = feats.get("ema_21")
        if ema9 is not None and ema21 is not None:
            score += 1 if ema9 > ema21 else -1

        rsi = feats.get("rsi")
        if rsi is not None:
            score += 1 if rsi > 50 else -1

        hist = feats.get("macd_histogram")
        if hist is not None:
            score += 1 if hist > 0 else -1

        if tf in ("H1", "H4", "D1"):
            ema200 = feats.get("ema_200")
            close_ = feats.get("close")
            if ema200 is not None and close_ is not None:
                score += 1 if close_ > ema200 else -1

    return max(-4, min(4, score))


async def get_htf_context(
    symbol: str,
    *,
    redis: aioredis.Redis,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    Fetch H1 + H4 + D1 features and summarise the higher-timeframe bias.

    Returns::

        {
            "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
            "h1": {...}, "h4": {...}, "d1": {...},
            "alignment_score": int,
        }
    """
    htf_list = ["H1", "H4", "D1"]
    feats = await aggregate_features(symbol, htf_list, redis=redis, as_of=as_of)

    alignment = calculate_mtf_trend_alignment(feats)
    if alignment >= 2:
        bias = "BULLISH"
    elif alignment <= -2:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "alignment_score": alignment,
        **{tf.lower(): feats.get(tf, {}) for tf in htf_list},
    }
