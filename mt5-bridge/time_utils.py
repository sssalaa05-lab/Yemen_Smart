"""Pure time/bar helpers for the Yemen Smart MT5 bridge.

MetaTrader5 Python returns epoch timestamps in UTC. Rates requested from
position zero include the current, still-forming bar as their final element;
consumers that need completed history must exclude that final element.
"""

from datetime import datetime, timezone
from typing import Any


def epoch_seconds_to_utc_iso(epoch_seconds: int | float) -> str:
    """Convert a UTC Unix timestamp to an ISO-8601 string with UTC offset."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def last_closed_rate(rates: Any) -> Any | None:
    """Return the newest completed rate, excluding the current (last) bar."""
    if rates is None or len(rates) < 2:
        return None
    return rates[-2]


def closed_rates(rates: Any) -> Any:
    """Return rates without the current, potentially incomplete final bar."""
    if rates is None or len(rates) < 2:
        return ()
    return rates[:-1]
