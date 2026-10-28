from __future__ import annotations

import sys
import unittest
from pathlib import Path


MT5_BRIDGE_DIR = Path(__file__).resolve().parents[1] / "mt5-bridge"
sys.path.insert(0, str(MT5_BRIDGE_DIR))

from time_utils import (  # noqa: E402
    closed_rates,
    epoch_seconds_to_utc_iso,
    last_closed_rate,
)


class MT5TimeAndBarTests(unittest.TestCase):
    def test_epoch_conversion_is_utc_without_broker_offset(self) -> None:
        # 2026-01-01 00:00:00 UTC. A legacy +2h broker offset must not shift it.
        self.assertEqual(
            epoch_seconds_to_utc_iso(1767225600),
            "2026-01-01T00:00:00+00:00",
        )

    def test_epoch_conversion_handles_fractional_seconds(self) -> None:
        self.assertEqual(
            epoch_seconds_to_utc_iso(1767225600.125),
            "2026-01-01T00:00:00.125000+00:00",
        )

    def test_last_closed_rate_excludes_current_bar(self) -> None:
        rates = [{"time": 100}, {"time": 200}, {"time": 300, "open": True}]
        self.assertEqual(last_closed_rate(rates), {"time": 200})
        self.assertEqual(closed_rates(rates), [{"time": 100}, {"time": 200}])

    def test_bar_helpers_require_current_and_previous_bar(self) -> None:
        self.assertIsNone(last_closed_rate(None))
        self.assertIsNone(last_closed_rate([{"time": 100}]))
        self.assertEqual(closed_rates([{"time": 100}]), ())


if __name__ == "__main__":
    unittest.main()
