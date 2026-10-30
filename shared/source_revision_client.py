"""Authenticated client for the append-only data-service revision archive."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from .http_client import new_client


async def submit_source_revisions(
    records: list[dict[str, Any]], *, caller_service: str,
) -> int:
    """Submit idempotent revision records; retries only safe transient failures."""
    if not records:
        return 0
    token = os.getenv("NEXUS_INTERNAL_SERVICE_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("NEXUS_INTERNAL_SERVICE_TOKEN must contain at least 32 characters")
    if caller_service not in {"nexus-news", "nexus-features"}:
        raise ValueError("unsupported source-revision caller")
    base_url = os.getenv("NEXUS_DATA_URL", "http://nexus-data:8001").rstrip("/")
    endpoint = f"{base_url}/api/data/ingest/source-revisions"
    accepted_total = 0
    async with new_client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
        for offset in range(0, len(records), 50):
            batch = records[offset:offset + 50]
            for attempt in range(3):
                try:
                    response = await client.post(
                        endpoint,
                        headers={"x-nexus-service-token": token},
                        json={"caller_service": caller_service, "records": batch},
                    )
                    response.raise_for_status()
                    accepted_total += int(response.json().get("accepted", 0))
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500 and exc.response.status_code != 429:
                        raise
                    if attempt == 2:
                        raise
                except httpx.RequestError:
                    if attempt == 2:
                        raise
                await asyncio.sleep(0.25 * (2 ** attempt))
    return accepted_total
