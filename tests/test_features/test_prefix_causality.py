from __future__ import annotations

import numpy as np
import pandas as pd

from services.nexus_features.indicators import calculate_all
from services.nexus_features.session_tagger import tag_dataframe
from services.nexus_features.volatility import (
    calculate_atr_normalized,
    calculate_bb_width,
    calculate_historical_vol,
    calculate_vol_percentile,
    detect_regime,
)


def _bars(n: int = 240) -> pd.DataFrame:
    i = np.arange(n, dtype=float)
    close = 100.0 + 0.04 * i + np.sin(i / 3.0) * 1.7 + np.cos(i / 11.0) * 0.6
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC").astype(str),
        "open": close - np.sin(i) * 0.2,
        "high": close + 0.35 + (i % 5) * 0.01,
        "low": close - 0.35 - (i % 7) * 0.01,
        "close": close,
        "volume": 100.0 + (i % 13) * 10.0,
    })


def test_indicator_session_and_volatility_outputs_are_prefix_causal() -> None:
    """Every historical output at T is invariant to rows after T."""
    bars = _bars()
    full = tag_dataframe(calculate_all(bars.copy()))
    full_volatility = pd.DataFrame({
        "atr_normalized": calculate_atr_normalized(bars),
        "bb_width": calculate_bb_width(bars),
        "historical_vol": calculate_historical_vol(bars),
        "vol_percentile": calculate_vol_percentile(bars),
        "regime": detect_regime(bars).astype(str),
    })
    generated = [c for c in full.columns if c not in bars.columns]
    numeric_generated = [c for c in generated if pd.api.types.is_numeric_dtype(full[c])]

    # Include every valid prefix after the long rolling warm-up; this covers
    # complete calculate_all output (EMA/RSI/MACD/BB/Stoch/VWAP/ATR/ADX/Ichimoku)
    # as well as session and volatility transforms.
    for end in range(205, len(bars) + 1):
        prefix_bars = bars.iloc[:end].copy()
        prefix = tag_dataframe(calculate_all(prefix_bars))
        expected = full.iloc[end - 1][numeric_generated].to_numpy(dtype=float)
        actual = prefix.iloc[-1][numeric_generated].to_numpy(dtype=float)
        np.testing.assert_allclose(
            actual, expected, rtol=1e-10, atol=1e-10, equal_nan=True,
            err_msg=f"feature values changed at prefix ending row {end - 1}",
        )
        assert prefix.iloc[-1]["session"] == full.iloc[end - 1]["session"]
        actual_vol = np.asarray([
            calculate_atr_normalized(prefix_bars).iloc[-1],
            calculate_bb_width(prefix_bars).iloc[-1],
            calculate_historical_vol(prefix_bars).iloc[-1],
            calculate_vol_percentile(prefix_bars).iloc[-1],
        ], dtype=float)
        expected_vol = full_volatility.iloc[end - 1, :4].to_numpy(dtype=float)
        np.testing.assert_allclose(actual_vol, expected_vol, rtol=1e-10, atol=1e-10, equal_nan=True)
        assert str(detect_regime(prefix_bars).iloc[-1]) == str(full_volatility.iloc[end - 1]["regime"])
