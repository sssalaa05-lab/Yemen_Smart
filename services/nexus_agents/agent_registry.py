"""In-memory agent activity registry.

Fixes the dead `_agent_statuses` dict that was never written to — the
dashboard flowchart relied on /api/agents/status to show agent liveness,
but the registry was always empty so every agent rendered OFFLINE.

Seeded with all 13 agents (A0-A12) as ``online`` once the service is up;
``safe_invoke`` in base_agent flips agents to ``processing`` while their
LLM call runs and back to ``online`` (or ``error``) when it finishes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# All 13 pipeline agents — seeded so the UI never shows the whole
# pipeline OFFLINE while the service itself is healthy.
AGENT_IDS: tuple[str, ...] = tuple(f"A{i}" for i in range(13))

_statuses: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed() -> None:
    """Mark every known agent online (service booted, pipeline ready)."""
    for aid in AGENT_IDS:
        _statuses.setdefault(aid, {"status": "online", "last_active": None})
    # keep existing activity entries if seed is called twice
    for aid in AGENT_IDS:
        _statuses[aid].setdefault("last_active", None)


def mark(agent_id: str, status: str) -> None:
    """Record an agent status transition with a fresh timestamp."""
    entry = _statuses.setdefault(agent_id, {"status": status, "last_active": None})
    entry["status"] = status
    entry["last_active"] = _now()


def snapshot() -> list[dict[str, Any]]:
    """Return the registry as a list of rows for the REST response."""
    seed()
    return [
        {"agent_id": aid, **entry}
        for aid, entry in sorted(_statuses.items())
    ]
