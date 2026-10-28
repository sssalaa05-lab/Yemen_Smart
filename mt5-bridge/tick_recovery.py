"""Durable cursor helpers for the MT5 range-tick collector.

The fingerprint is a deduplication aid, not a guaranteed source event ID:
MT5 tick records do not expose a unique ticket for every market-data event.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def tick_fingerprint(tick: dict[str, Any]) -> str:
    """Stable composite fingerprint from the MT5 fields actually returned."""
    fields = ("time_msc", "bid", "ask", "last", "volume", "volume_real", "flags")
    normalized = {key: tick.get(key) for key in fields}
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def tick_utc_iso(time_msc: int) -> str:
    return datetime.fromtimestamp(int(time_msc) / 1000, tz=timezone.utc).isoformat()


def plan_query_window(
    covered_through_ms: int | None,
    now_ms: int,
    *,
    initial_lookback_ms: int,
    window_ms: int,
    overlap_ms: int,
) -> tuple[int, int]:
    """Plan a bounded, intentionally overlapping inclusive MT5 query range."""
    if window_ms <= 0 or initial_lookback_ms < 0 or overlap_ms < 0:
        raise ValueError("tick range durations must be non-negative and window_ms > 0")
    if covered_through_ms is None:
        start_ms = max(0, now_ms - initial_lookback_ms)
        return start_ms, min(now_ms, start_ms + window_ms)
    start_ms = max(0, int(covered_through_ms) - overlap_ms)
    end_ms = min(now_ms, int(covered_through_ms) + window_ms)
    if end_ms <= start_ms:
        raise ValueError("query window has no forward coverage")
    return start_ms, end_ms


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [items[i:i + size] for i in range(0, len(items), size)] or [[]]


class WatermarkStore:
    """Atomic JSON sidecar storing coverage cursors and last observed contracts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {"version": 1, "watermarks": {}, "contracts": {}}
        self._load()

    def _load(self) -> None:
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and parsed.get("version") == 1:
                watermarks = parsed.get("watermarks", {})
                contracts = parsed.get("contracts", {})
                if isinstance(watermarks, dict) and isinstance(contracts, dict):
                    self.data = {"version": 1, "watermarks": watermarks, "contracts": contracts}
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError):
            # Keep the corrupt file untouched; no cursor is trusted or advanced.
            self.data["state_error"] = "unreadable_state_file"

    def get_watermark(self, key: str) -> int | None:
        value = self.data["watermarks"].get(key)
        return int(value) if value is not None else None

    def commit_watermark(self, key: str, covered_through_ms: int) -> None:
        prior = self.get_watermark(key)
        if prior is not None and covered_through_ms < prior:
            raise ValueError("watermark cannot move backwards")
        self.data["watermarks"][key] = int(covered_through_ms)
        self._save()

    def get_contract(self, key: str) -> dict[str, Any] | None:
        value = self.data["contracts"].get(key)
        return value if isinstance(value, dict) else None

    def set_contract(self, key: str, snapshot: dict[str, Any]) -> None:
        self.data["contracts"][key] = snapshot
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f"{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(self.data, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
