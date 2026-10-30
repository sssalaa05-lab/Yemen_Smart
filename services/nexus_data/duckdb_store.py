"""
DuckDB persistent storage for ticks and OHLCV bars.

All heavy I/O is offloaded to a thread-pool so the event loop stays free.
Includes automatic data-retention pruning.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from shared.models import Tick, OHLCV

log = structlog.get_logger("nexus_data.duckdb")

try:
    import duckdb  # type: ignore[import-untyped]
except ImportError:
    duckdb = None  # type: ignore[assignment]

_POOL = ThreadPoolExecutor(max_workers=2)

# Retention: keep ticks for 7 days, OHLCV for 365 days
TICK_RETENTION_DAYS = 7
OHLCV_RETENTION_DAYS = 365


class DataStore:
    """Async-friendly DuckDB wrapper for market-data persistence."""

    def __init__(self, db_path: str = "./data/nexus.duckdb") -> None:
        self._db_path = db_path
        self._conn: Any | None = None
        self._lock = threading.RLock()

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def _recover_stale_wal(self, db_path: str) -> None:
        """Checkpoint or remove a large WAL left by an unclean shutdown (Windows)."""
        wal_path = Path(f"{db_path}.wal")
        if not wal_path.exists():
            return
        wal_mb = wal_path.stat().st_size / (1024 * 1024)
        if wal_mb < 5:
            return

        await log.awarning("duckdb.large_wal_detected", path=str(wal_path), size_mb=round(wal_mb, 1))

        def _checkpoint() -> bool:
            try:
                conn = duckdb.connect(db_path)
                try:
                    conn.execute("CHECKPOINT")
                finally:
                    conn.close()
                return True
            except Exception:
                return False

        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(_POOL, _checkpoint)
        if ok:
            await log.ainfo("duckdb.wal_checkpoint_ok", path=db_path)
            return

        if os.getenv("NEXUS_DUCKDB_WAL_RECOVERY", "1").lower() in ("1", "true", "yes"):
            try:
                wal_path.unlink(missing_ok=True)
                await log.awarning("duckdb.wal_removed_for_recovery", path=str(wal_path))
            except OSError as exc:
                await log.awarning("duckdb.wal_remove_failed", error=str(exc))

    async def init_tables(self, *, timeout_s: float = 60.0) -> None:
        if duckdb is None:
            raise RuntimeError("duckdb package is not installed")

        db_path = str(Path(self._db_path).resolve())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path

        await self._recover_stale_wal(db_path)

        loop = asyncio.get_running_loop()
        try:
            # Single attempt — retries after a hung connect leave orphan threads
            # holding the DuckDB file lock on Windows.
            self._conn = await asyncio.wait_for(
                loop.run_in_executor(_POOL, lambda: duckdb.connect(db_path)),
                timeout=timeout_s,
            )
            await asyncio.wait_for(
                loop.run_in_executor(_POOL, self._create_schemas),
                timeout=timeout_s,
            )
        except TimeoutError as exc:
            self.close()
            raise RuntimeError(
                f"DuckDB open timed out after {timeout_s}s ({db_path}). "
                "Kill stray python.exe processes, delete data/nexus.duckdb.wal, "
                "then restart."
            ) from exc
        except Exception:
            self.close()
            raise

        await log.ainfo("duckdb.tables_ready", path=db_path)

    def _create_schemas(self) -> None:
        assert self._conn is not None
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                symbol     VARCHAR   NOT NULL,
                bid        DOUBLE    NOT NULL,
                ask        DOUBLE    NOT NULL,
                spread     DOUBLE    NOT NULL DEFAULT 0,
                timestamp  TIMESTAMP WITH TIME ZONE NOT NULL,
                source_id  VARCHAR,
                provider   VARCHAR,
                broker     VARCHAR,
                server     VARCHAR,
                logical_symbol VARCHAR,
                raw_symbol VARCHAR,
                contract_snapshot_id VARCHAR,
                time_msc   BIGINT,
                last       DOUBLE,
                volume     DOUBLE,
                volume_real DOUBLE,
                flags      BIGINT
            )
        """)
        for column, dtype in (
            ("source_id", "VARCHAR"), ("provider", "VARCHAR"),
            ("broker", "VARCHAR"), ("server", "VARCHAR"),
            ("logical_symbol", "VARCHAR"), ("raw_symbol", "VARCHAR"),
            ("contract_snapshot_id", "VARCHAR"), ("time_msc", "BIGINT"),
            ("last", "DOUBLE"), ("volume", "DOUBLE"),
            ("volume_real", "DOUBLE"), ("flags", "BIGINT"),
        ):
            self._conn.execute(f"ALTER TABLE ticks ADD COLUMN IF NOT EXISTS {column} {dtype}")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol     VARCHAR   NOT NULL,
                timeframe  VARCHAR   NOT NULL,
                open       DOUBLE    NOT NULL,
                high       DOUBLE    NOT NULL,
                low        DOUBLE    NOT NULL,
                close      DOUBLE    NOT NULL,
                volume     DOUBLE    NOT NULL DEFAULT 0,
                timestamp  TIMESTAMP WITH TIME ZONE NOT NULL,
                source_id  VARCHAR,
                provider   VARCHAR,
                broker     VARCHAR,
                server     VARCHAR,
                logical_symbol VARCHAR,
                raw_symbol VARCHAR,
                contract_snapshot_id VARCHAR,
                real_volume DOUBLE
            )
        """)
        for column, dtype in (
            ("source_id", "VARCHAR"), ("provider", "VARCHAR"),
            ("broker", "VARCHAR"), ("server", "VARCHAR"),
            ("logical_symbol", "VARCHAR"), ("raw_symbol", "VARCHAR"),
            ("contract_snapshot_id", "VARCHAR"), ("real_volume", "DOUBLE"),
        ):
            self._conn.execute(f"ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS {column} {dtype}")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS contract_snapshots (
                snapshot_id VARCHAR PRIMARY KEY,
                source_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                broker VARCHAR,
                server VARCHAR,
                logical_symbol VARCHAR NOT NULL,
                raw_symbol VARCHAR NOT NULL,
                observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
                spec_json JSON NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_revisions (
                event_id VARCHAR NOT NULL,
                revision_id VARCHAR NOT NULL,
                event_time TIMESTAMP WITH TIME ZONE,
                available_at TIMESTAMP WITH TIME ZONE NOT NULL,
                source VARCHAR NOT NULL,
                event_json JSON NOT NULL,
                PRIMARY KEY (event_id, revision_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS source_revisions (
                dataset VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                entity_id VARCHAR NOT NULL,
                revision_id VARCHAR NOT NULL,
                source_record_id VARCHAR,
                event_time TIMESTAMP WITH TIME ZONE,
                period_start TIMESTAMP WITH TIME ZONE,
                period_end TIMESTAMP WITH TIME ZONE,
                published_at TIMESTAMP WITH TIME ZONE,
                available_at TIMESTAMP WITH TIME ZONE NOT NULL,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL,
                caller_service VARCHAR NOT NULL,
                identity_quality VARCHAR NOT NULL,
                quality_status VARCHAR NOT NULL,
                unit VARCHAR,
                currency VARCHAR,
                region VARCHAR,
                schema_version INTEGER NOT NULL,
                ingest_run_id VARCHAR,
                supersedes_revision_id VARCHAR,
                payload_hash VARCHAR NOT NULL,
                payload JSON NOT NULL,
                PRIMARY KEY (dataset, provider, entity_id, revision_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS source_ticks (
                source_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                broker VARCHAR,
                server VARCHAR,
                logical_symbol VARCHAR NOT NULL,
                raw_symbol VARCHAR NOT NULL,
                contract_snapshot_id VARCHAR,
                time_msc BIGINT NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                fingerprint VARCHAR NOT NULL,
                bid DOUBLE NOT NULL,
                ask DOUBLE NOT NULL,
                last DOUBLE NOT NULL DEFAULT 0,
                volume DOUBLE NOT NULL DEFAULT 0,
                volume_real DOUBLE NOT NULL DEFAULT 0,
                flags BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (source_id, raw_symbol, time_msc, fingerprint)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tick_batch_chunks (
                source_id VARCHAR NOT NULL,
                raw_symbol VARCHAR NOT NULL,
                batch_id VARCHAR NOT NULL,
                window_start_ms BIGINT NOT NULL,
                window_end_ms BIGINT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                tick_count INTEGER NOT NULL,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL,
                PRIMARY KEY (source_id, raw_symbol, batch_id, chunk_index)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tick_ingestion_windows (
                source_id VARCHAR NOT NULL,
                raw_symbol VARCHAR NOT NULL,
                batch_id VARCHAR NOT NULL,
                window_start_ms BIGINT NOT NULL,
                covered_through_ms BIGINT NOT NULL,
                chunk_count INTEGER NOT NULL,
                tick_count INTEGER NOT NULL,
                recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                PRIMARY KEY (source_id, raw_symbol, batch_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          VARCHAR PRIMARY KEY,
                symbol      VARCHAR   NOT NULL,
                side        VARCHAR   NOT NULL,
                entry_price DOUBLE    NOT NULL,
                exit_price  DOUBLE    NOT NULL,
                pnl_pips    DOUBLE    NOT NULL DEFAULT 0,
                pnl_usd     DOUBLE    NOT NULL DEFAULT 0,
                rr_ratio    DOUBLE    NOT NULL DEFAULT 0,
                duration_s  DOUBLE    NOT NULL DEFAULT 0,
                session     VARCHAR,
                conviction  DOUBLE    NOT NULL DEFAULT 0,
                opened_at   TIMESTAMP NOT NULL,
                closed_at   TIMESTAMP NOT NULL
            )
        """)
        # Migration for DBs created before per-strategy attribution existed.
        self._conn.execute(
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy VARCHAR DEFAULT ''"
        )
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
            ON ticks (symbol, timestamp DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts
            ON ohlcv (symbol, timeframe, timestamp DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_closed_at
            ON trades (closed_at DESC)
        """)
        # Flush WAL after unclean shutdown so the next open is fast on Windows.
        try:
            self._conn.execute("CHECKPOINT")
        except Exception:
            pass

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Insert ───────────────────────────────────────────────────────────

    async def insert_tick(self, tick: Tick) -> None:
        await self._run(
            "INSERT INTO ticks (symbol, bid, ask, spread, timestamp, source_id, provider, "
            "broker, server, logical_symbol, raw_symbol, contract_snapshot_id, time_msc, "
            "last, volume, volume_real, flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tick.symbol, tick.bid, tick.ask, tick.spread, tick.timestamp, tick.source_id,
             tick.provider, tick.broker, tick.server, tick.logical_symbol, tick.raw_symbol,
             tick.contract_snapshot_id, tick.time_msc, tick.last, tick.volume,
             tick.volume_real, tick.flags),
        )

    async def insert_ohlcv(self, bar: OHLCV) -> None:
        await self._run(
            "INSERT INTO ohlcv "
            "(symbol, timeframe, open, high, low, close, volume, timestamp, source_id, provider, "
            "broker, server, logical_symbol, raw_symbol, contract_snapshot_id, real_volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bar.symbol, bar.timeframe, bar.open, bar.high,
                bar.low, bar.close, bar.volume, bar.timestamp, bar.source_id,
                bar.provider, bar.broker, bar.server, bar.logical_symbol,
                bar.raw_symbol, bar.contract_snapshot_id, bar.real_volume,
            ),
        )

    async def persist_tick_batch_chunk(
        self,
        *,
        source: dict[str, Any],
        contract_snapshot: dict[str, Any] | None,
        batch_id: str,
        window_start_ms: int,
        window_end_ms: int,
        chunk_index: int,
        chunk_count: int,
        ticks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Idempotently persist a chunk; ack coverage only after all chunks exist."""
        if chunk_count < 1 or not 0 <= chunk_index < chunk_count:
            raise ValueError("invalid tick batch chunk coordinates")
        loop = asyncio.get_running_loop()

        def _job() -> dict[str, Any]:
            assert self._conn is not None
            with self._lock:
                conn = self._conn
                conn.execute("BEGIN TRANSACTION")
                try:
                    if contract_snapshot:
                        conn.execute(
                            "INSERT INTO contract_snapshots "
                            "(snapshot_id, source_id, provider, broker, server, logical_symbol, "
                            "raw_symbol, observed_at, spec_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT (snapshot_id) DO NOTHING",
                            (contract_snapshot["snapshot_id"], source["source_id"],
                             source["provider"], source.get("broker"), source.get("server"),
                             source["logical_symbol"], source["raw_symbol"],
                             datetime.fromisoformat(contract_snapshot["observed_at"]),
                             json.dumps(contract_snapshot["specs"], sort_keys=True)),
                        )
                    for tick in ticks:
                        normalized_ts = datetime.fromisoformat(tick["timestamp"])
                        snapshot_id = contract_snapshot.get("snapshot_id") if contract_snapshot else None
                        time_msc = int(tick["time_msc"])
                        fingerprint = tick["fingerprint"]
                        conn.execute(
                            "INSERT INTO source_ticks "
                            "(source_id, provider, broker, server, logical_symbol, raw_symbol, "
                            "contract_snapshot_id, time_msc, timestamp, fingerprint, bid, ask, "
                            "last, volume, volume_real, flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT (source_id, raw_symbol, time_msc, fingerprint) DO NOTHING",
                            (source["source_id"], source["provider"], source.get("broker"),
                             source.get("server"), source["logical_symbol"], source["raw_symbol"],
                             snapshot_id, time_msc, normalized_ts,
                             fingerprint, float(tick["bid"]), float(tick["ask"]),
                             float(tick.get("last") or 0), float(tick.get("volume") or 0),
                             float(tick.get("volume_real") or 0), int(tick.get("flags") or 0)),
                        )
                        conn.execute(
                            "INSERT INTO ticks (symbol, bid, ask, spread, timestamp, source_id, provider, "
                            "broker, server, logical_symbol, raw_symbol, contract_snapshot_id, time_msc, "
                            "last, volume, volume_real, flags) "
                            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
                            "WHERE NOT EXISTS (SELECT 1 FROM ticks WHERE source_id=? AND raw_symbol=? "
                            "AND time_msc=? AND bid=? AND ask=? AND last=? AND volume=? AND volume_real=? AND flags=?)",
                            (source["logical_symbol"], float(tick["bid"]), float(tick["ask"]),
                             float(tick["ask"]) - float(tick["bid"]), normalized_ts,
                             source["source_id"], source["provider"], source.get("broker"),
                             source.get("server"), source["logical_symbol"], source["raw_symbol"],
                             snapshot_id, time_msc, float(tick.get("last") or 0),
                             float(tick.get("volume") or 0), float(tick.get("volume_real") or 0),
                             int(tick.get("flags") or 0), source["source_id"], source["raw_symbol"],
                             time_msc, float(tick["bid"]), float(tick["ask"]),
                             float(tick.get("last") or 0), float(tick.get("volume") or 0),
                             float(tick.get("volume_real") or 0), int(tick.get("flags") or 0)),
                        )
                    prior = conn.execute(
                        "SELECT chunk_count, window_start_ms, window_end_ms FROM tick_batch_chunks "
                        "WHERE source_id=? AND raw_symbol=? AND batch_id=? LIMIT 1",
                        (source["source_id"], source["raw_symbol"], batch_id),
                    ).fetchone()
                    if prior and tuple(map(int, prior)) != (chunk_count, window_start_ms, window_end_ms):
                        raise ValueError("batch_id reused with different range metadata")
                    conn.execute(
                        "INSERT INTO tick_batch_chunks "
                        "(source_id, raw_symbol, batch_id, window_start_ms, window_end_ms, "
                        "chunk_index, chunk_count, tick_count, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (source_id, raw_symbol, batch_id, chunk_index) DO NOTHING",
                        (source["source_id"], source["raw_symbol"], batch_id, window_start_ms,
                         window_end_ms, chunk_index, chunk_count, len(ticks), datetime.now(timezone.utc)),
                    )
                    counts = conn.execute(
                        "SELECT COUNT(DISTINCT chunk_index), COALESCE(SUM(tick_count), 0) "
                        "FROM tick_batch_chunks WHERE source_id=? AND raw_symbol=? AND batch_id=? "
                        "AND chunk_count=? AND window_start_ms=? AND window_end_ms=?",
                        (source["source_id"], source["raw_symbol"], batch_id,
                         chunk_count, window_start_ms, window_end_ms),
                    ).fetchone()
                    complete = int(counts[0]) == chunk_count
                    total_ticks = int(counts[1])
                    if complete:
                        conn.execute(
                            "INSERT INTO tick_ingestion_windows "
                            "(source_id, raw_symbol, batch_id, window_start_ms, covered_through_ms, "
                            "chunk_count, tick_count, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT (source_id, raw_symbol, batch_id) DO UPDATE SET "
                            "tick_count=excluded.tick_count, recorded_at=excluded.recorded_at",
                            (source["source_id"], source["raw_symbol"], batch_id, window_start_ms,
                             window_end_ms, chunk_count, total_ticks, datetime.now(timezone.utc)),
                        )
                    conn.execute("COMMIT")
                    return {
                        "accepted": len(ticks), "received": len(ticks), "rejected": 0,
                        "chunk_index": chunk_index, "chunk_count": chunk_count,
                        "window_complete": complete,
                        "covered_through_ms": window_end_ms if complete else None,
                        "tick_count_in_window": total_ticks if complete else None,
                        "coverage_is_completeness_proof": False,
                    }
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        return await loop.run_in_executor(_POOL, _job)

    async def persist_source_bars(
        self,
        *,
        source: dict[str, Any],
        contract_snapshot: dict[str, Any] | None,
        bars: list[dict[str, Any]],
    ) -> None:
        """Persist broker identity and contract snapshot before logical aliasing."""
        loop = asyncio.get_running_loop()

        def _job() -> None:
            assert self._conn is not None
            with self._lock:
                conn = self._conn
                conn.execute("BEGIN TRANSACTION")
                try:
                    if contract_snapshot:
                        conn.execute(
                            "INSERT INTO contract_snapshots "
                            "(snapshot_id, source_id, provider, broker, server, logical_symbol, "
                            "raw_symbol, observed_at, spec_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT (snapshot_id) DO NOTHING",
                            (contract_snapshot["snapshot_id"], source["source_id"], source["provider"],
                             source.get("broker"), source.get("server"), source["logical_symbol"],
                             source["raw_symbol"], datetime.fromisoformat(contract_snapshot["observed_at"]),
                             json.dumps(contract_snapshot["specs"], sort_keys=True)),
                        )
                    for bar in bars:
                        conn.execute(
                            "INSERT INTO ohlcv (symbol, timeframe, open, high, low, close, volume, timestamp, "
                            "source_id, provider, broker, server, logical_symbol, raw_symbol, "
                            "contract_snapshot_id, real_volume) "
                            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
                            "WHERE NOT EXISTS (SELECT 1 FROM ohlcv WHERE symbol=? AND timeframe=? AND timestamp=? "
                            "AND source_id=? AND server IS NOT DISTINCT FROM ? AND raw_symbol=?)",
                            (source["logical_symbol"], bar["timeframe"], float(bar["open"]),
                             float(bar["high"]), float(bar["low"]), float(bar["close"]),
                             float(bar.get("volume") or 0), datetime.fromisoformat(bar["timestamp"]),
                             source["source_id"], source["provider"], source.get("broker"),
                             source.get("server"), source["logical_symbol"], source["raw_symbol"],
                             contract_snapshot.get("snapshot_id") if contract_snapshot else None,
                             float(bar.get("real_volume") or 0), source["logical_symbol"],
                             bar["timeframe"], datetime.fromisoformat(bar["timestamp"]),
                             source["source_id"], source.get("server"), source["raw_symbol"]),
                        )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        await loop.run_in_executor(_POOL, _job)

    async def persist_calendar_revisions(self, events: list[dict[str, Any]]) -> int:
        """Append observed calendar vintages without replacing previous revisions."""
        if not events:
            return 0
        loop = asyncio.get_running_loop()

        def _job() -> int:
            assert self._conn is not None
            with self._lock:
                conn = self._conn
                conn.execute("BEGIN TRANSACTION")
                try:
                    before = int(conn.execute("SELECT COUNT(*) FROM calendar_revisions").fetchone()[0])
                    for event in events:
                        event_time = event.get("time")
                        def _utc(value: str | None) -> datetime | None:
                            if not value:
                                return None
                            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            return parsed.astimezone(timezone.utc)
                        conn.execute(
                            "INSERT INTO calendar_revisions "
                            "(event_id, revision_id, event_time, available_at, source, event_json) "
                            "SELECT ?, ?, ?, ?, ?, ? WHERE NOT EXISTS ("
                            "SELECT 1 FROM calendar_revisions WHERE event_id=? AND revision_id=?)",
                            (event["event_id"], event["revision_id"], _utc(event_time),
                             _utc(event["available_at"]),
                             str(event.get("source") or "mt5_calendar"),
                             json.dumps(event, sort_keys=True), event["event_id"], event["revision_id"]),
                        )
                    conn.execute("COMMIT")
                    after = int(conn.execute("SELECT COUNT(*) FROM calendar_revisions").fetchone()[0])
                    return after - before
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        return await loop.run_in_executor(_POOL, _job)

    async def persist_source_revisions(
        self, records: list[dict[str, Any]], *, caller_service: str,
    ) -> int:
        """Atomically append point-in-time source vintages; never rewrite a revision."""
        if not records:
            return 0
        allowed_datasets = {"news", "economic", "fundamental", "cross_asset"}

        def _time(value: Any, field: str, *, required: bool = False) -> datetime | None:
            if value is None or value == "":
                if required:
                    raise ValueError(f"{field} is required")
                return None
            if isinstance(value, datetime):
                parsed = value
            elif isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError(f"invalid {field}") from exc
            else:
                raise ValueError(f"invalid {field}")
            if parsed.tzinfo is None:
                raise ValueError(f"{field} must include a timezone")
            return parsed.astimezone(timezone.utc)

        normalized: list[tuple[Any, ...]] = []
        seen: dict[tuple[str, str, str, str], str] = {}
        received_at = datetime.now(timezone.utc)
        caller = str(caller_service or "").strip()[:64]
        if not caller:
            raise ValueError("caller_service is required")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("each source revision must be an object")
            dataset = str(record.get("dataset") or "").strip().lower()
            provider = str(record.get("provider") or "").strip()[:200]
            entity_id = str(record.get("entity_id") or "").strip()[:512]
            revision_id = str(record.get("revision_id") or "").strip()[:256]
            if dataset not in allowed_datasets or not all((provider, entity_id, revision_id)):
                raise ValueError("unsupported dataset or missing source identity")
            payload = record.get("payload")
            if not isinstance(payload, (dict, list)):
                raise ValueError("payload must be an object or array")
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if len(payload_json.encode("utf-8")) > 262_144:
                raise ValueError("source revision payload exceeds 256 KiB")
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            key = (dataset, provider, entity_id, revision_id)
            prior_hash = seen.get(key)
            if prior_hash is not None and prior_hash != payload_hash:
                raise ValueError("revision identity reused with conflicting payloads")
            if prior_hash is not None:
                continue
            seen[key] = payload_hash
            normalized.append((
                dataset, provider, entity_id, revision_id,
                str(record.get("source_record_id") or "")[:512] or None,
                _time(record.get("event_time"), "event_time"),
                _time(record.get("period_start"), "period_start"),
                _time(record.get("period_end"), "period_end"),
                _time(record.get("published_at"), "published_at"),
                _time(record.get("available_at"), "available_at", required=True),
                received_at, caller,
                str(record.get("identity_quality") or "derived")[:32],
                str(record.get("quality_status") or "observed")[:32],
                str(record.get("unit") or "")[:64] or None,
                str(record.get("currency") or "")[:16] or None,
                str(record.get("region") or "")[:32] or None,
                int(record.get("schema_version") or 1),
                str(record.get("ingest_run_id") or "")[:128] or None,
                str(record.get("supersedes_revision_id") or "")[:256] or None,
                payload_hash, payload_json,
            ))

        loop = asyncio.get_running_loop()

        def _job() -> int:
            assert self._conn is not None
            with self._lock:
                conn = self._conn
                conn.execute("BEGIN TRANSACTION")
                inserted = 0
                try:
                    for row in normalized:
                        key = row[:4]
                        existing = conn.execute(
                            "SELECT payload_hash FROM source_revisions "
                            "WHERE dataset=? AND provider=? AND entity_id=? AND revision_id=?",
                            key,
                        ).fetchone()
                        if existing:
                            if existing[0] != row[-2]:
                                raise ValueError("revision identity conflicts with stored payload")
                            continue
                        conn.execute(
                            "INSERT INTO source_revisions (dataset, provider, entity_id, revision_id, "
                            "source_record_id, event_time, period_start, period_end, published_at, available_at, "
                            "received_at, caller_service, identity_quality, quality_status, unit, currency, region, "
                            "schema_version, ingest_run_id, supersedes_revision_id, payload_hash, payload) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            row,
                        )
                        inserted += 1
                    conn.execute("COMMIT")
                    return inserted
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        return await loop.run_in_executor(_POOL, _job)

    async def query_source_revisions_asof(
        self, dataset: str, decision_time: datetime, *, provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return latest available revision per provider/entity at decision_time."""
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must include a timezone")
        query = """
            SELECT dataset, provider, entity_id, revision_id, source_record_id, event_time,
                   period_start, period_end, published_at, available_at, received_at, caller_service,
                   identity_quality, quality_status, unit, currency, region, schema_version, ingest_run_id,
                   supersedes_revision_id, payload_hash, payload
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY provider, entity_id
                    ORDER BY available_at DESC, received_at DESC, revision_id DESC
                ) AS rn
                FROM source_revisions WHERE dataset=? AND available_at<=?
            ) ranked WHERE rn=1
        """
        params: tuple[Any, ...] = (dataset, decision_time.astimezone(timezone.utc))
        if provider:
            query = query.replace("WHERE rn=1", "WHERE rn=1 AND provider=?")
            params += (provider,)
        rows = await self._fetch(query, params)
        columns = [
            "dataset", "provider", "entity_id", "revision_id", "source_record_id", "event_time",
            "period_start", "period_end", "published_at", "available_at", "received_at", "caller_service",
            "identity_quality", "quality_status", "unit", "currency", "region", "schema_version",
            "ingest_run_id", "supersedes_revision_id", "payload_hash", "payload",
        ]
        result = []
        for row in rows:
            item = dict(zip(columns, row))
            if isinstance(item["payload"], str):
                item["payload"] = json.loads(item["payload"])
            result.append(item)
        return result

    async def dedupe_ohlcv(self) -> int:
        """Remove duplicate (symbol, timeframe, timestamp) rows; return removed count."""
        loop = asyncio.get_running_loop()

        def _job() -> int:
            assert self._conn is not None
            with self._lock:
                before = self._conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
                self._conn.execute(
                    "DELETE FROM ohlcv WHERE rowid IN ("
                    "SELECT rowid FROM ("
                    "  SELECT rowid, row_number() OVER "
                    "    (PARTITION BY symbol, timeframe, timestamp, COALESCE(source_id, ''), "
                    "     COALESCE(server, ''), COALESCE(raw_symbol, '') ORDER BY rowid) AS rn "
                    "  FROM ohlcv) WHERE rn > 1)"
                )
                after = self._conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
                return before - after

        return await loop.run_in_executor(_POOL, _job)

    async def insert_batch(self, items: list[Tick | OHLCV]) -> None:
        if not items:
            return

        loop = asyncio.get_running_loop()

        def _bulk() -> None:
            assert self._conn is not None
            with self._lock:
                for item in items:
                    if isinstance(item, Tick):
                        self._conn.execute(
                            "INSERT INTO ticks (symbol, bid, ask, spread, timestamp, source_id, provider, "
                            "broker, server, logical_symbol, raw_symbol, contract_snapshot_id, time_msc, "
                            "last, volume, volume_real, flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (item.symbol, item.bid, item.ask, item.spread, item.timestamp, item.source_id,
                             item.provider, item.broker, item.server, item.logical_symbol, item.raw_symbol,
                             item.contract_snapshot_id, item.time_msc, item.last, item.volume,
                             item.volume_real, item.flags),
                        )
                    elif isinstance(item, OHLCV):
                        self._conn.execute(
                            "INSERT INTO ohlcv "
                            "(symbol, timeframe, open, high, low, close, volume, timestamp, source_id, provider, "
                            "broker, server, logical_symbol, raw_symbol, contract_snapshot_id, real_volume) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                item.symbol, item.timeframe, item.open, item.high,
                                item.low, item.close, item.volume, item.timestamp, item.source_id,
                                item.provider, item.broker, item.server, item.logical_symbol,
                                item.raw_symbol, item.contract_snapshot_id, item.real_volume,
                            ),
                        )

        await loop.run_in_executor(_POOL, _bulk)

    async def insert_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl_pips: float,
        pnl_usd: float,
        rr_ratio: float,
        duration_s: float,
        session: str,
        conviction: float,
        opened_at: datetime,
        closed_at: datetime,
        strategy: str = "",
    ) -> None:
        await self._run(
            "INSERT INTO trades "
            "(id, symbol, side, entry_price, exit_price, pnl_pips, pnl_usd, "
            "rr_ratio, duration_s, session, conviction, opened_at, closed_at, strategy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING",
            (
                trade_id, symbol, side, entry_price, exit_price,
                pnl_pips, pnl_usd, rr_ratio, duration_s,
                session, conviction, opened_at, closed_at, strategy,
            ),
        )

    # ── Query ────────────────────────────────────────────────────────────

    async def query_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> list[OHLCV]:
        conditions = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [symbol, timeframe]

        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = " AND ".join(conditions)
        sql = (
            f"SELECT symbol, timeframe, open, high, low, close, volume, timestamp, "
            f"source_id, provider, broker, server, logical_symbol, raw_symbol, contract_snapshot_id, real_volume "
            f"FROM ohlcv WHERE {where} "
            f"QUALIFY row_number() OVER (PARTITION BY timestamp, COALESCE(source_id, ''), "
            f"COALESCE(server, ''), COALESCE(raw_symbol, '') ORDER BY rowid) = 1 "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        rows = await self._fetch(sql, tuple(params))
        return [
            OHLCV(
                symbol=r[0], timeframe=r[1],
                open=r[2], high=r[3], low=r[4], close=r[5],
                volume=r[6], timestamp=r[7], source_id=r[8], provider=r[9],
                broker=r[10], server=r[11], logical_symbol=r[12], raw_symbol=r[13],
                contract_snapshot_id=r[14], real_volume=r[15],
            )
            for r in rows
        ]

    async def query_trades(
        self,
        symbol: str | None = None,
        session: str | None = None,
        since: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        if session:
            conditions.append("session = ?")
            params.append(session)
        if since:
            conditions.append("closed_at >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        count_rows = await self._fetch(
            f"SELECT COUNT(*) FROM trades {where}", tuple(params)
        )
        total = count_rows[0][0] if count_rows else 0

        offset = (page - 1) * page_size
        rows = await self._fetch(
            f"SELECT id, symbol, side, entry_price, exit_price, pnl_pips, pnl_usd, "
            f"rr_ratio, duration_s, session, conviction, opened_at, closed_at, strategy "
            f"FROM trades {where} ORDER BY closed_at DESC LIMIT ? OFFSET ?",
            tuple([*params, page_size, offset]),
        )
        cols = [
            "id", "symbol", "side", "entry_price", "exit_price", "pnl_pips",
            "pnl_usd", "rr_ratio", "duration_s", "session", "conviction",
            "opened_at", "closed_at", "strategy",
        ]
        trades = []
        for row in rows:
            d = dict(zip(cols, row))
            for k in ("opened_at", "closed_at"):
                if d[k] is not None:
                    d[k] = d[k].isoformat() if hasattr(d[k], "isoformat") else str(d[k])
            trades.append(d)
        return {"trades": trades, "total": total, "page": page, "page_size": page_size}

    async def query_latest_ticks(
        self, symbol: str, count: int = 50,
    ) -> list[Tick]:
        rows = await self._fetch(
            "SELECT symbol, bid, ask, spread, timestamp, source_id, provider, broker, server, "
            "logical_symbol, raw_symbol, contract_snapshot_id, time_msc, last, volume, volume_real, flags "
            "FROM ticks WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, count),
        )
        return [
            Tick(symbol=r[0], bid=r[1], ask=r[2], spread=r[3], timestamp=r[4],
                 source_id=r[5], provider=r[6], broker=r[7], server=r[8],
                 logical_symbol=r[9], raw_symbol=r[10], contract_snapshot_id=r[11],
                 time_msc=r[12], last=r[13], volume=r[14], volume_real=r[15], flags=r[16])
            for r in rows
        ]

    async def get_performance_metrics(self) -> dict[str, Any]:
        rows = await self._fetch(
            """
            SELECT
                COALESCE(SUM(pnl_usd), 0)                        AS total_pnl,
                COUNT(*)                                          AS total_trades,
                COALESCE(AVG(CASE WHEN pnl_usd > 0 THEN pnl_usd END), 0) AS avg_win,
                COALESCE(AVG(CASE WHEN pnl_usd <= 0 THEN pnl_usd END), 0) AS avg_loss,
                CASE WHEN COUNT(*) > 0
                     THEN ROUND(SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)
                     ELSE 0 END AS win_rate,
                CASE WHEN ABS(COALESCE(SUM(CASE WHEN pnl_usd <= 0 THEN pnl_usd END), 1)) > 0
                     THEN ROUND(COALESCE(SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd END), 0)
                          / ABS(COALESCE(SUM(CASE WHEN pnl_usd <= 0 THEN pnl_usd END), 1)), 2)
                     ELSE 0 END AS profit_factor
            FROM trades
            """
        )
        if not rows or not rows[0]:
            return {}
        row = rows[0]
        cols = ["total_pnl", "total_trades", "avg_win", "avg_loss", "win_rate", "profit_factor"]
        return dict(zip(cols, row))

    async def get_pnl_curve(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self._fetch(
            """
            WITH recent AS (
                SELECT closed_at, pnl_usd
                FROM trades
                ORDER BY closed_at DESC
                LIMIT ?
            )
            SELECT
                closed_at,
                pnl_usd,
                SUM(pnl_usd) OVER (
                    ORDER BY closed_at ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS cumulative_pnl
            FROM recent
            ORDER BY closed_at ASC
            """,
            (limit,),
        )
        return [
            {
                "closed_at": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "pnl_usd": r[1],
                "cumulative_pnl": r[2],
            }
            for r in rows
        ]

    async def get_daily_pnl(self, since: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE closed_at >= ?" if since else ""
        params = (since,) if since else ()
        rows = await self._fetch(
            f"""
            SELECT
                CAST(closed_at AS DATE) AS date,
                COALESCE(SUM(pnl_usd), 0) AS pnl,
                COUNT(*) AS trades,
                COALESCE(ROUND(
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)
                    * 100.0 / NULLIF(COUNT(*), 0), 2), 0) AS win_rate
            FROM trades {where}
            GROUP BY CAST(closed_at AS DATE)
            ORDER BY date DESC
            """,
            params,
        )
        return [
            {"date": str(r[0]), "pnl": r[1], "trades": r[2], "win_rate": r[3]}
            for r in rows
        ]

    async def get_grouped_performance(self, group_col: str) -> list[dict[str, Any]]:
        safe_col = group_col if group_col in ("session", "symbol") else "session"
        rows = await self._fetch(
            f"""
            SELECT
                {safe_col} AS grp,
                COALESCE(SUM(pnl_usd), 0) AS total_pnl,
                COUNT(*) AS trades,
                COALESCE(ROUND(
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)
                    * 100.0 / NULLIF(COUNT(*), 0), 2), 0) AS win_rate,
                COALESCE(AVG(rr_ratio), 0) AS avg_rr
            FROM trades
            GROUP BY {safe_col}
            ORDER BY total_pnl DESC
            """,
        )
        return [
            {"group": r[0], "total_pnl": r[1], "trades": r[2],
             "win_rate": r[3], "avg_rr": r[4]}
            for r in rows
        ]

    # ── Retention ────────────────────────────────────────────────────────

    async def prune_old_data(self) -> None:
        tick_cutoff = datetime.now(timezone.utc) - timedelta(days=TICK_RETENTION_DAYS)
        ohlcv_cutoff = datetime.now(timezone.utc) - timedelta(days=OHLCV_RETENTION_DAYS)

        await self._run(
            "DELETE FROM ticks WHERE timestamp < ?", (tick_cutoff,),
        )
        await self._run(
            "DELETE FROM ohlcv WHERE timestamp < ?", (ohlcv_cutoff,),
        )
        await log.ainfo(
            "duckdb.pruned",
            tick_cutoff=str(tick_cutoff),
            ohlcv_cutoff=str(ohlcv_cutoff),
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _run(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        loop = asyncio.get_running_loop()

        def _exec() -> None:
            assert self._conn is not None
            with self._lock:
                self._conn.execute(sql, params)

        await loop.run_in_executor(_POOL, _exec)

    async def _fetch(
        self, sql: str, params: tuple[Any, ...] = (),
    ) -> list[tuple[Any, ...]]:
        loop = asyncio.get_running_loop()

        def _query() -> list[tuple[Any, ...]]:
            assert self._conn is not None
            with self._lock:
                return self._conn.execute(sql, params).fetchall()

        return await loop.run_in_executor(_POOL, _query)
