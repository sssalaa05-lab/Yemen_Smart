#!/usr/bin/env python3
"""Set runtime settings for the offline demo via the project's own
runtime_settings module (exact Redis key + coercion guaranteed)."""
import asyncio
import os
import sys

PROJECT = "/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main"
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT, ".env"))

from shared.runtime_settings import update_settings  # noqa: E402


async def main() -> None:
    patch = {
        # Offline demo on synthetic data: relax the conviction gate so the
        # full decision chain (signals -> agents -> risk -> paper orders)
        # is exercised. Sanctioned live-edit knob used by the dashboard.
        "min_conviction_override": 0.52,
    }
    merged = await update_settings(patch)
    print("runtime settings updated:")
    for k in ("min_conviction_override", "risk_per_trade_pct", "max_open_positions",
              "max_daily_trades", "llm_provider"):
        print(f"  {k} = {merged.get(k)}")


asyncio.run(main())
