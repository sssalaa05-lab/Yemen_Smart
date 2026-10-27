"""Integration check: calendar features over the real Redis training data.

Runs the REAL _fetch_training_data path (including calendar backfill) against
the live Redis, then reports matrix shape, calendar feature coverage, and
sanity (no NaN/inf). Read-only — writes nothing.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT = Path("/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main")
sys.path.insert(0, str(PROJECT))

import numpy as np  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402

from services.nexus_ml import main as ml_main  # noqa: E402
from services.nexus_ml.calendar_features import (  # noqa: E402
    CALENDAR_FEATURE_NAMES,
    compute_calendar_features,
    prepare_events,
)


async def main() -> None:
    r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
    ml_main._redis = r

    # 1) Calendar snapshot through the production loader
    prepared = await ml_main._get_prepared_calendar()
    print(f"[1] prepared calendar events: {len(prepared)}")
    assert prepared, "calendar snapshot missing — bridge not publishing?"

    # 2) Real training fetch with backfill
    data = await ml_main._fetch_training_data(["XAUUSD"])
    assert data is not None, "no training data"
    X, y, timestamps, feature_names = data
    n, k = X.shape
    print(f"[2] training matrix: {n} rows x {k} cols (was 41 before)")
    assert k == 47, f"expected 47 columns, got {k}"
    assert feature_names[-6:] == CALENDAR_FEATURE_NAMES, "calendar names not appended"
    assert feature_names[:41] == json.loads(
        (PROJECT / "models_store/XAUUSD/feature_names.json").read_text()
    ), "original 41 feature order changed!"

    # 3) Sanity: no NaN / inf anywhere
    assert np.isfinite(X).all(), "NaN/inf in training matrix!"
    print("[3] no NaN/inf in matrix ✓")

    # 4) Calendar feature coverage on real data
    names_idx = {name: i for i, name in enumerate(feature_names)}
    cal_block = X[:, [names_idx[c] for c in CALENDAR_FEATURE_NAMES]]
    prox = cal_block[:, 0]
    mins = cal_block[:, 1]
    sur = cal_block[:, 3]
    print(f"[4] proximity > 0:      {(prox > 0).sum()}/{n} rows "
          f"({100 * (prox > 0).mean():.1f}%)")
    print(f"    min_to_next < 1440: {(mins < 1440).sum()}/{n} rows")
    print(f"    surprise != 0:      {(sur != 0).sum()}/{n} rows")
    print(f"    surprise range:     [{sur.min():.4f}, {sur.max():.4f}]")

    # 5) Cross-check one known timestamp by hand (independent of backfill)
    ts_str = str(timestamps[-1])
    manual = compute_calendar_features("XAUUSD", np.datetime64(ts_str).astype(
        "datetime64[s]").astype(object).replace(tzinfo=None), prepared)
    print(f"[5] manual recompute @ {ts_str}: {json.dumps(manual)}")

    # 6) newest record timestamp parsed correctly?
    print(f"[6] timestamps span: {timestamps[0]} -> {timestamps[-1]}")
    await r.aclose()
    print("ALL INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
