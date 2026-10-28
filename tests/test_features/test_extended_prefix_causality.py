from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from services.nexus_features.cross_asset import compute_cross_asset_features
from services.nexus_features.institutional_features import NexusInstitutionalFeatures
from services.nexus_features.key_levels import detect_order_blocks, detect_sr_levels
from services.nexus_features.main import _closed_ohlcv_frame
from services.nexus_features.multi_timeframe import aggregate_features
from services.nexus_features.trend_analyzer import find_swing_points


class _MemoryRedis:
    def __init__(self, values: dict[str, str]):
        self.values = values
        self.writes: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.writes[key] = value
        return True


def _hourly_bars(count: int = 240) -> list[dict]:
    i = np.arange(count, dtype=float)
    close = 100.0 + 0.03 * i + np.sin(i / 5.0)
    timestamps = pd.date_range("2026-01-01", periods=count, freq="h", tz="UTC")
    return [
        {
            "timestamp": ts.isoformat(),
            "open": float(c - 0.1),
            "high": float(c + 0.4),
            "low": float(c - 0.4),
            "close": float(c),
            "volume": float(100 + (j % 7)),
        }
        for j, (ts, c) in enumerate(zip(timestamps, close))
    ]


def test_mtf_uses_sorted_closed_bars_no_later_than_decision_time() -> None:
    bars = _hourly_bars()
    latest_closed = bars[-1]["timestamp"]
    decision_time = pd.Timestamp(latest_closed) + pd.Timedelta(hours=1)
    forming_bar = {
        **bars[-1],
        "timestamp": decision_time.isoformat(),
        "close": 900.0,
        "high": 901.0,
        "low": 899.0,
        "open": 900.0,
    }
    future_bar = {
        **forming_bar,
        "timestamp": (decision_time + pd.Timedelta(hours=1)).isoformat(),
        "close": 1200.0,
    }
    # Deliberately reverse input order: the selected row must be the latest
    # timestamp whose entire bar interval ended at or before decision_time.
    redis = _MemoryRedis({"nexus:ohlcv:XAUUSD:H1": json.dumps([future_bar, forming_bar, *bars[::-1]])})
    result = asyncio.run(aggregate_features(
        "XAUUSD", ["H1"], redis=redis, as_of=decision_time.to_pydatetime(),
    ))
    assert result["H1"]["_source_bar_timestamp"] == latest_closed
    assert result["H1"]["_available_at"] == decision_time.isoformat()


def test_feature_service_closed_bar_gate_rejects_open_and_untimed_bars() -> None:
    bars = pd.DataFrame(_hourly_bars(4))
    decision_time = pd.Timestamp(bars.iloc[-1]["timestamp"]) + pd.Timedelta(minutes=30)
    closed = _closed_ohlcv_frame(bars, "H1", decision_time.to_pydatetime())
    assert len(closed) == 3
    assert closed.iloc[-1]["timestamp"].isoformat() == bars.iloc[-2]["timestamp"]
    assert _closed_ohlcv_frame(bars.drop(columns=["timestamp"]), "H1", decision_time.to_pydatetime()).empty


def test_swing_point_is_not_reported_until_right_hand_confirmation_bars_exist() -> None:
    n = 16
    highs = np.full(n, 90.0)
    lows = np.full(n, 80.0)
    highs[10] = 110.0
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC").astype(str),
        "high": highs,
        "low": lows,
        "close": (highs + lows) / 2.0,
    })
    before_confirmation = find_swing_points(frame.iloc[:15], order=5)
    confirmed = find_swing_points(frame, order=5)
    assert not any(point.kind == "HIGH" and point.index == 10 for point in before_confirmation)
    assert not any(abs(level.price - 110.0) < 0.01 for level in detect_sr_levels(frame.iloc[:15], order=5, tolerance=0.1))
    point = next(point for point in confirmed if point.kind == "HIGH" and point.index == 10)
    assert point.confirmation_index == 15
    assert point.confirmed_at == frame.iloc[15]["timestamp"]
    assert any(abs(level.price - 110.0) < 0.01 for level in detect_sr_levels(frame, order=5, tolerance=0.1))


def test_order_block_is_available_at_impulse_close_not_origin_candle() -> None:
    n = 25
    open_ = np.full(n, 100.0)
    close = np.full(n, 100.1)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)
    open_[23], close[23] = 100.2, 99.8
    open_[24], close[24] = 99.8, 103.0
    high[24], low[24] = 103.1, 99.7
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC").astype(str),
        "open": open_, "high": high, "low": low, "close": close,
    })
    assert not detect_order_blocks(frame.iloc[:24])
    blocks = detect_order_blocks(frame)
    block = next(block for block in blocks if block.index == 23)
    assert block.confirmation_index == 24
    assert block.confirmed_at == frame.iloc[24]["timestamp"]


def test_cross_asset_snapshot_uses_only_the_supplied_gold_prefix() -> None:
    now = datetime.now(timezone.utc).isoformat()
    redis = _MemoryRedis({
        "nexus:cross_asset:DXY": json.dumps({
            "level": 104.0, "change_5d": 0.2, "rsi_14": 48.0,
            "trend_score": 0.3, "fetched_at": now, "source": "test_snapshot",
        }),
        "nexus:cross_asset:US10Y": json.dumps({
            "level": 4.1, "change_5d": 0.01, "fetched_at": now, "source": "test_snapshot",
        }),
    })
    prices = np.array([100.0 + np.sin(i / 3) + i * 0.02 for i in range(40)])
    cut = 25
    prefix_features = asyncio.run(compute_cross_asset_features("XAUUSD", redis, prices[:cut]))
    mutated_suffix = prices.copy()
    mutated_suffix[cut:] += 1_000.0
    same_decision_features = asyncio.run(compute_cross_asset_features("XAUUSD", redis, mutated_suffix[:cut]))
    assert prefix_features["gold_dxy_divergence"] == same_decision_features["gold_dxy_divergence"]
    assert prefix_features["corr_gold_dxy_20"] == same_decision_features["corr_gold_dxy_20"]


def test_cross_asset_rejects_snapshots_observed_after_decision_time() -> None:
    decision = datetime.now(timezone.utc)
    future = (pd.Timestamp(decision) + pd.Timedelta(minutes=2)).isoformat()
    redis = _MemoryRedis({
        "nexus:cross_asset:DXY": json.dumps({
            "level": 110.0, "change_5d": 3.0, "rsi_14": 80.0,
            "trend_score": 1.0, "fetched_at": future, "source": "future_snapshot",
        }),
        "nexus:cross_asset:US10Y": json.dumps({
            "level": 6.0, "change_5d": 1.0, "fetched_at": future, "source": "future_snapshot",
        }),
    })
    features = asyncio.run(compute_cross_asset_features(
        "XAUUSD", redis, np.linspace(100.0, 102.0, 30), decision_time=decision,
    ))
    assert features["cross_asset_available"] == 0
    assert features["cross_asset_source"] == "unavailable_asof"
    assert features["dxy_change_5d"] == 0.0


def test_institutional_price_features_are_deterministic_on_each_asof_prefix() -> None:
    engine = NexusInstitutionalFeatures()
    prices = np.array([100.0 + 0.04 * i + np.sin(i / 2.5) for i in range(180)])
    equity = [100.0 + i * 0.1 for i in range(30)]
    for end in (60, 90, 130, len(prices)):
        prefix = prices[:end]
        first = engine.compute_all(prefix, equity, win_rate=0.55, avg_win_pips=12.0,
                                   avg_loss_pips=9.0, account_equity=200.0)
        second = engine.compute_all(prefix.copy(), equity.copy(), win_rate=0.55, avg_win_pips=12.0,
                                    avg_loss_pips=9.0, account_equity=200.0)
        assert first == second
        assert first["tick_imbalance"]["tick_imbalance"] == engine.tick_rule_imbalance(prefix)["tick_imbalance"]
        assert first["rv_ratio"]["rv_ratio"] == engine.realized_volatility_ratio(prefix)["rv_ratio"]
