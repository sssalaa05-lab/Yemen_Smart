from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from services.nexus_data.duckdb_store import DataStore

UTC = timezone.utc


def _record(revision: str, available_at: str, value: float, *, entity: str = "article-1") -> dict:
    return {
        "dataset": "news",
        "provider": "ExampleWire",
        "entity_id": entity,
        "revision_id": revision,
        "source_record_id": "wire-42",
        "published_at": "2026-10-30T08:00:00Z",
        "available_at": available_at,
        "identity_quality": "provider",
        "quality_status": "observed",
        "schema_version": 1,
        "payload": {"headline": "A headline", "sentiment": value},
    }


def test_source_revisions_are_append_only_idempotent_and_point_in_time(tmp_path) -> None:
    store = DataStore(str(tmp_path / "pit.duckdb"))

    async def run() -> None:
        await store.init_tables()
        try:
            first = _record("rev-1", "2026-10-30T09:00:00Z", 0.1)
            second = _record("rev-2", "2026-10-30T11:00:00Z", 0.9)
            assert await store.persist_source_revisions([first], caller_service="nexus-news") == 1
            assert await store.persist_source_revisions([first], caller_service="nexus-news") == 0
            assert await store.persist_source_revisions([second], caller_service="nexus-news") == 1

            before = await store.query_source_revisions_asof(
                "news", datetime(2026, 10, 30, 10, 0, tzinfo=UTC),
            )
            after = await store.query_source_revisions_asof(
                "news", datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
            )
            assert [row["revision_id"] for row in before] == ["rev-1"]
            assert before[0]["payload"]["sentiment"] == 0.1
            assert [row["revision_id"] for row in after] == ["rev-2"]
            assert after[0]["available_at"].isoformat().startswith("2026-10-30T11:00:00")
        finally:
            store.close()

    asyncio.run(run())


def test_source_revision_key_collision_rolls_back_whole_batch(tmp_path) -> None:
    store = DataStore(str(tmp_path / "collision.duckdb"))

    async def run() -> None:
        await store.init_tables()
        try:
            original = _record("rev-1", "2026-10-30T09:00:00Z", 0.1)
            await store.persist_source_revisions([original], caller_service="nexus-news")

            conflicting = _record("rev-1", "2026-10-30T09:00:00Z", 0.8)
            new_record = _record("rev-2", "2026-10-30T10:00:00Z", 0.4, entity="article-2")
            with pytest.raises(ValueError, match="conflicts with stored payload"):
                await store.persist_source_revisions(
                    [new_record, conflicting], caller_service="nexus-news",
                )

            rows = await store.query_source_revisions_asof(
                "news", datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
            )
            assert [(row["entity_id"], row["revision_id"]) for row in rows] == [
                ("article-1", "rev-1"),
            ]
            assert rows[0]["payload"]["sentiment"] == 0.1
        finally:
            store.close()

    asyncio.run(run())


def test_source_revision_rejects_naive_availability_timestamp(tmp_path) -> None:
    store = DataStore(str(tmp_path / "invalid-time.duckdb"))

    async def run() -> None:
        await store.init_tables()
        try:
            invalid = _record("rev-1", "2026-10-30T09:00:00", 0.1)
            with pytest.raises(ValueError, match="timezone"):
                await store.persist_source_revisions([invalid], caller_service="nexus-news")
        finally:
            store.close()

    asyncio.run(run())
