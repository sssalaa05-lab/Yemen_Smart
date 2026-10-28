"""
Nexus ML — FastAPI service (port 8003).

Exposes REST endpoints for prediction, training, and model status.
Runs a background Redis Stream consumer that listens for FeatureEvents,
runs the ensemble, and publishes SignalEvents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import redis.asyncio as aioredis
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.constants import (
    HEARTBEAT_INTERVAL_SEC,
    STREAM_MAX_LEN,
    RedisStream,
    ServiceName,
    Verdict,
)
from shared.events import FeatureEvent, SignalEvent

from .calendar_features import (
    CALENDAR_FEATURE_NAMES,
    enrich_features_with_calendar,
    has_calendar_features,
    prepare_events,
)
from .ensemble import EnsembleSignal, ModelEnsemble
from .rule_based_signal import RuleBasedSignalGenerator
from .training import WalkForwardConfig, WalkForwardTrainer
from .training_data import (
    build_pending_sample,
    finalize_next_bar_sample,
    is_eligible_training_record,
    parse_utc_timestamp,
    sanitize_training_features,
    training_schema_is_safe,
)

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MODEL_DIR = os.getenv("MODEL_DIR", "./models_store")
MODEL_PROMOTION_TOKEN = os.getenv("NEXUS_ML_PROMOTION_TOKEN", "").strip()
CONSUMER_GROUP = "nexus_ml_group"
CONSUMER_NAME = "nexus_ml_worker_1"

# ── Pydantic request / response schemas ──────────────────────────────────────


class PredictResponse(BaseModel):
    symbol: str
    direction: str
    confidence: float
    regime: str
    anomaly_score: float
    is_anomaly: bool
    individual_scores: dict[str, float] = Field(default_factory=dict)
    sentiment: dict[str, float] = Field(default_factory=dict)
    top_features: list[str] = Field(default_factory=list)


class TrainRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["EURUSD"])
    train_months: int = 6
    val_months: int = 1
    step_months: int = 1


class PromoteCandidateRequest(BaseModel):
    symbol: str
    candidate_id: str
    confirmation: str


class TrainResponse(BaseModel):
    status: str
    message: str
    task_id: str = ""


class ModelStatusResponse(BaseModel):
    models: dict[str, bool]
    ensemble_loaded: bool
    rule_based_active: bool = False
    symbol: str = ""
    per_symbol: dict[str, dict[str, bool]] = {}


class HealthResponse(BaseModel):
    service: str
    status: str
    uptime_seconds: float
    models_loaded: dict[str, bool]


# ── Application state ────────────────────────────────────────────────────────

_ensemble: ModelEnsemble | None = None
_rule_based: RuleBasedSignalGenerator | None = None
_redis: aioredis.Redis | None = None
_start_time: float = 0.0
_consumer_task: asyncio.Task[None] | None = None
_training_in_progress: bool = False
_last_signal_ts: dict[str, float] = {}
SIGNAL_COOLDOWN_SEC = int(os.getenv("NEXUS_ML_SIGNAL_COOLDOWN_SEC", "60"))

# Auto-retrain config
_RETRAIN_MIN_SAMPLES = int(os.getenv("NEXUS_RETRAIN_MIN_SAMPLES", "500"))
_RETRAIN_CHECK_INTERVAL = int(os.getenv("NEXUS_RETRAIN_CHECK_INTERVAL_SEC", "3600"))
_RETRAIN_COOLDOWN_HOURS = int(os.getenv("NEXUS_RETRAIN_COOLDOWN_HOURS", "24"))
_RETRAIN_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("NEXUS_SYMBOLS", os.getenv("STREAM_SYMBOLS", "XAUUSD")).split(",")
    if s.strip()
]
_RETRAIN_LAST_KEY = "nexus:ml:last_retrain_ts"

# ── Calendar / news-surprise feature cache ───────────────────────────────────
# The MT5 economic calendar snapshot (nexus:calendar:mt5) is republished by
# the bridge every 5 minutes; a 300 s TTL keeps this in lockstep without
# hammering Redis on every M5 bar.
_CAL_CACHE_TTL_SEC = 300.0
_cal_cache: dict[str, Any] = {"prepared": [], "fetched_at": 0.0, "count": 0}


async def _get_prepared_calendar() -> list[dict[str, Any]]:
    """Load + parse the calendar snapshot with a short-lived module cache.

    Returns a pre-parsed event list for calendar_features.compute_*(). Falls
    back to the last good snapshot on Redis errors; empty list when no
    calendar has ever been published (features degrade to neutral values).
    """
    assert _redis is not None
    now = time.time()
    if _cal_cache["prepared"] and (now - _cal_cache["fetched_at"]) < _CAL_CACHE_TTL_SEC:
        return _cal_cache["prepared"]  # type: ignore[return-value]

    events: list[dict[str, Any]] = []
    for key in ("nexus:calendar:mt5", "news:calendar"):
        try:
            raw = await _redis.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if isinstance(data, dict):
                data = data.get("events", [])
            if isinstance(data, list) and data:
                events = data
                break
        except Exception:
            logger.debug("Calendar snapshot read failed for %s", key, exc_info=True)

    prepared = prepare_events(events)
    _cal_cache.update(prepared=prepared, fetched_at=now, count=len(events))
    if events:
        logger.info(
            "Calendar features: %d raw events -> %d parsed (source refreshed)",
            len(events), len(prepared),
        )
    return prepared

# ── Per-symbol model registry ────────────────────────────────────────────────
# Each symbol trains and loads its own ensemble from models_store/<SYMBOL>/.
# Gold ($4k, ATR ~$5) and BTC ($64k, ATR ~$31) have incomparable scales — a
# model fitted on one produces meaningless predictions for the other.

_ensembles: dict[str, ModelEnsemble] = {}


def _has_directional_ml_model(status: dict[str, bool]) -> bool:
    """Sentiment's lazy-loaded placeholder alone is not a trained predictor."""
    return any(
        loaded for name, loaded in status.items()
        if name != "sentiment"
    )


def symbol_model_dir(symbol: str) -> Path:
    return Path(MODEL_DIR) / symbol.strip().upper()


def candidate_model_dir(task_id: str, symbol: str) -> Path:
    """Immutable-by-convention candidate location, isolated from champion files."""
    return Path(MODEL_DIR) / "candidates" / task_id / symbol.strip().upper()


def _write_candidate_receipt(
    task_id: str, symbol: str, result_count: int, source: str,
) -> Path:
    import hashlib

    directory = candidate_model_dir(task_id, symbol)
    schema_path = directory / "training_schema.json"
    if not schema_path.is_file():
        raise RuntimeError("candidate lacks leakage-safe training schema receipt")
    schema_bytes = schema_path.read_bytes()
    receipt = {
        "candidate_id": task_id,
        "symbol": symbol.strip().upper(),
        "source": source,
        "status": "candidate_pending_approval",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fold_count": int(result_count),
        "training_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
    }
    path = directory / "candidate_receipt.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return path


def _get_symbol_ensemble(symbol: str) -> ModelEnsemble:
    """Return (creating+loading on first use) the ensemble for a symbol."""
    key = symbol.strip().upper()
    ens = _ensembles.get(key)
    if ens is None:
        ens = ModelEnsemble(model_dir=str(symbol_model_dir(key)))
        try:
            ens.load_all_models()
        except Exception:
            logger.warning("Ensemble load failed for %s", key, exc_info=True)
        _ensembles[key] = ens
    return ens


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ensemble, _rule_based, _redis, _start_time, _consumer_task

    _start_time = time.time()
    from shared import setup_logger as _setup_logger
    _setup_logger("nexus-ml", level=os.getenv("LOG_LEVEL", "INFO"))

    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Connected to Redis at %s", REDIS_URL)

    # Per-symbol ensembles: each symbol keeps its own trained models under
    # models_store/<SYMBOL>/. Gold and BTC have completely different price
    # scales and dynamics, so one shared model would predict garbage for
    # whichever symbol it wasn't fitted on. _ensemble stays bound to the
    # first configured symbol for backwards compatibility with callers that
    # don't pass one.
    for sym in _RETRAIN_SYMBOLS:
        ens = _get_symbol_ensemble(sym)
        logger.info("Ensemble[%s] model load status: %s", sym, ens.models_status())
    _ensemble = _get_symbol_ensemble(_RETRAIN_SYMBOLS[0]) if _RETRAIN_SYMBOLS else ModelEnsemble(model_dir=MODEL_DIR)
    status = _ensemble.models_status()

    # Rule-based fallback for when no ML models are trained yet
    _rule_based = RuleBasedSignalGenerator(confidence_threshold=0.35)
    any_model_loaded = _has_directional_ml_model(status)
    if not any_model_loaded:
        logger.warning(
            "No ML models loaded — using rule-based signal generator (real indicators)"
        )

    await _ensure_consumer_group()
    _consumer_task = asyncio.create_task(_stream_consumer())
    asyncio.create_task(_heartbeat_loop())
    asyncio.create_task(_auto_retrain_loop())

    logger.info("nexus-ml service started on port 8003")

    # Start parallel model traders (ML/DL/RL) background scheduler
    try:
        from .traders_api import startup_traders, shutdown_traders
        await startup_traders()
        logger.info("Parallel model traders initialised")
    except Exception as _te:
        logger.warning("Traders startup skipped: %s", _te)

    yield

    # Shutdown traders scheduler
    try:
        from .traders_api import shutdown_traders
        await shutdown_traders()
    except Exception:
        pass

    if _consumer_task:
        _consumer_task.cancel()
    if _redis:
        await _redis.aclose()
    logger.info("nexus-ml service shut down")


app = FastAPI(
    title="Nexus ML Pipeline",
    version="2.0.0",
    lifespan=lifespan,
)

# ── Parallel Model Traders (ML / DL / RL) ───────────────────────────────────
try:
    from .traders_api import router as traders_router
    app.include_router(traders_router)
    logger.info("Parallel model traders API mounted at /api/traders")
except Exception as _traders_exc:
    logger.warning("Traders API not available: %s", _traders_exc)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        service=ServiceName.ML,
        status="healthy",
        uptime_seconds=round(time.time() - _start_time, 2),
        models_loaded=_ensemble.models_status() if _ensemble else {},
    )


# ── Prediction endpoint ──────────────────────────────────────────────────────


@app.get("/api/ml/predict/{symbol}", response_model=PredictResponse)
async def predict(symbol: str):
    features = await _get_latest_features(symbol)
    if features is None:
        raise HTTPException(404, f"No cached features for {symbol}")

    # Live calendar/news-surprise context for the current moment. Must match
    # the columns the trainer produces (feature_names.json) — extra keys are
    # ignored by ensembles trained before this feature existed.
    try:
        prepared = await _get_prepared_calendar()
        if prepared:
            enrich_features_with_calendar(symbol, features, prepared)
    except Exception:
        logger.debug("Calendar enrichment skipped in predict", exc_info=True)

    ensemble = _get_symbol_ensemble(symbol)
    any_model_loaded = _has_directional_ml_model(ensemble.models_status())

    if any_model_loaded:
        feature_array = ensemble.build_feature_array(features)
        signal = ensemble.predict(feature_array)
    elif _rule_based is not None:
        signal = _rule_based.predict(features)
    else:
        raise HTTPException(503, "No signal generator available")

    return PredictResponse(
        symbol=symbol,
        direction=signal.direction,
        confidence=signal.confidence,
        regime=signal.regime,
        anomaly_score=signal.anomaly_score,
        is_anomaly=signal.is_anomaly,
        individual_scores=signal.individual_scores,
        sentiment=signal.sentiment,
        top_features=signal.top_features,
    )


# ── Training endpoint ────────────────────────────────────────────────────────


@app.post("/api/ml/train", response_model=TrainResponse)
async def train(req: TrainRequest, background_tasks: BackgroundTasks):
    global _training_in_progress

    if _training_in_progress:
        raise HTTPException(409, "Training already in progress")

    import uuid
    task_id = uuid.uuid4().hex[:12]
    _training_in_progress = True

    background_tasks.add_task(_run_training, req, task_id)

    return TrainResponse(
        status="started",
        message=f"Candidate-only walk-forward training started for {req.symbols}; champion remains unchanged",
        task_id=task_id,
    )


@app.get("/api/ml/candidates/{candidate_id}")
async def candidate_status(candidate_id: str):
    if not candidate_id.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid candidate id")
    root = Path(MODEL_DIR) / "candidates" / candidate_id
    if not root.is_dir():
        raise HTTPException(404, "candidate not found")
    receipts = []
    for receipt_path in sorted(root.glob("*/candidate_receipt.json")):
        try:
            receipts.append(json.loads(receipt_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return {"candidate_id": candidate_id, "status": "candidate_pending_approval", "symbols": receipts}


@app.post("/api/ml/models/promote")
async def promote_candidate(
    req: PromoteCandidateRequest,
    x_ml_promotion_token: str = Header(default=""),
):
    """Promote one reviewed candidate; disabled unless an approval secret is configured."""
    import hashlib
    import re
    import tempfile

    if not MODEL_PROMOTION_TOKEN:
        raise HTTPException(503, "candidate promotion is disabled: configure NEXUS_ML_PROMOTION_TOKEN")
    if x_ml_promotion_token != MODEL_PROMOTION_TOKEN:
        raise HTTPException(403, "invalid promotion approval token")
    symbol = req.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9._-]{1,32}", symbol):
        raise HTTPException(400, "invalid symbol")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", req.candidate_id):
        raise HTTPException(400, "invalid candidate id")
    if req.confirmation != f"PROMOTE {symbol} {req.candidate_id}":
        raise HTTPException(400, "confirmation phrase does not match requested candidate")

    candidate = candidate_model_dir(req.candidate_id, symbol)
    receipt_path = candidate / "candidate_receipt.json"
    schema_path = candidate / "training_schema.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        schema_bytes = schema_path.read_bytes()
        schema = json.loads(schema_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(404, "candidate receipt/schema unavailable") from exc
    expected_hash = hashlib.sha256(schema_bytes).hexdigest()
    if (receipt.get("candidate_id") != req.candidate_id
            or receipt.get("symbol") != symbol
            or receipt.get("training_schema_sha256") != expected_hash
            or not training_schema_is_safe(schema)):
        raise HTTPException(409, "candidate receipt or safe schema validation failed")

    champion = symbol_model_dir(symbol)
    versions = Path(MODEL_DIR) / "versions" / symbol
    versions.mkdir(parents=True, exist_ok=True)
    version_dir = versions / req.candidate_id
    if version_dir.exists():
        raise HTTPException(409, "candidate version already promoted")
    shutil.copytree(candidate, version_dir)
    champion.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{symbol}.promotion-", dir=champion.parent))
    shutil.rmtree(temp_dir)
    shutil.copytree(candidate, temp_dir)
    backup: Path | None = None
    try:
        if champion.exists():
            backup = versions / f"pre-{req.candidate_id}"
            if backup.exists():
                raise FileExistsError(f"backup version exists: {backup}")
            os.replace(champion, backup)
        os.replace(temp_dir, champion)
    except Exception:
        if backup is not None and backup.exists() and not champion.exists():
            os.replace(backup, champion)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    _ensembles.pop(symbol, None)
    loaded_status = _get_symbol_ensemble(symbol).models_status()
    return {"status": "promoted", "symbol": symbol, "candidate_id": req.candidate_id,
            "previous_champion_version": backup.name if backup else None,
            "loaded_models": loaded_status}


async def _run_training(req: TrainRequest, task_id: str) -> None:
    """Train isolated candidate artifacts; champion changes require promotion."""
    global _training_in_progress
    try:
        logger.info("[%s] Training started for %s", task_id, req.symbols)

        for symbol in req.symbols:
            sym = symbol.strip().upper()
            out_dir = candidate_model_dir(task_id, sym)
            out_dir.mkdir(parents=True, exist_ok=True)

            data = await _fetch_training_data([sym])
            if data is None:
                logger.error("[%s] No training data for %s — skipped", task_id, sym)
                continue

            cfg = WalkForwardConfig(
                train_months=req.train_months,
                val_months=req.val_months,
                step_months=req.step_months,
                model_dir=str(out_dir),
            )
            trainer = WalkForwardTrainer(cfg)

            X, y, timestamps, feature_names, target_timestamps = data
            results = trainer.train_all_models(
                X, y, timestamps, feature_names, target_timestamps=target_timestamps,
            )
            logger.info("[%s] %s trained — %d folds → %s", task_id, sym, len(results), out_dir)
            if results:
                _write_candidate_receipt(task_id, sym, len(results), source="redis_live_history")

    except Exception:
        logger.error("[%s] Training failed", task_id, exc_info=True)
    finally:
        _training_in_progress = False


# ── Model status endpoint ────────────────────────────────────────────────────


@app.get("/api/ml/models/status", response_model=ModelStatusResponse)
async def models_status(symbol: str | None = None):
    """Model status. Without `symbol` reports the first configured symbol;
    `per_symbol` always carries every configured symbol's own ensemble."""
    target = (symbol or (_RETRAIN_SYMBOLS[0] if _RETRAIN_SYMBOLS else "XAUUSD")).upper()
    status = _get_symbol_ensemble(target).models_status()
    any_loaded = any(status.values())
    per_symbol = {
        sym: _get_symbol_ensemble(sym).models_status()
        for sym in _RETRAIN_SYMBOLS
    }
    return ModelStatusResponse(
        models=status,
        ensemble_loaded=any_loaded,
        rule_based_active=not any_loaded and _rule_based is not None,
        symbol=target,
        per_symbol=per_symbol,
    )


@app.get("/api/ml/retrain/status")
async def retrain_status():
    """Auto-retrain state: last run, sample counts, next trigger threshold."""
    if _redis is None:
        raise HTTPException(503, "Redis not connected")

    total_samples = 0
    per_symbol: dict[str, int] = {}
    for sym in _RETRAIN_SYMBOLS:
        n = await _redis.llen(f"nexus:features:history:{sym}")
        per_symbol[sym] = n
        total_samples += n

    last_result_raw = await _redis.get("nexus:ml:last_retrain_result")
    last_result = json.loads(last_result_raw) if last_result_raw else None

    last_ts_raw = await _redis.get(_RETRAIN_LAST_KEY)
    last_ts = float(last_ts_raw) if last_ts_raw else None

    return {
        "total_samples": total_samples,
        "per_symbol": per_symbol,
        "min_samples_required": _RETRAIN_MIN_SAMPLES,
        "ready_to_train": total_samples >= _RETRAIN_MIN_SAMPLES and not _training_in_progress,
        "training_in_progress": _training_in_progress,
        "last_retrain_ts": last_ts,
        "last_retrain_result": last_result,
        "retrain_cooldown_hours": _RETRAIN_COOLDOWN_HOURS,
        "check_interval_sec": _RETRAIN_CHECK_INTERVAL,
    }


# ── Redis Stream consumer ────────────────────────────────────────────────────


async def _ensure_consumer_group() -> None:
    assert _redis is not None
    try:
        await _redis.xgroup_create(
            RedisStream.FEATURE_STREAM, CONSUMER_GROUP, id="0", mkstream=True,
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def _stream_consumer() -> None:
    """Continuously read FeatureEvents, run predictions, publish SignalEvents."""
    assert _redis is not None
    assert _ensemble is not None or _rule_based is not None

    logger.info("Stream consumer started — listening on %s", RedisStream.FEATURE_STREAM)

    while True:
        try:
            entries = await _redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={RedisStream.FEATURE_STREAM: ">"},
                count=10,
                block=2000,
            )

            if not entries:
                continue

            for _stream_name, messages in entries:
                for msg_id, raw in messages:
                    await _handle_feature_event(msg_id, raw)

        except asyncio.CancelledError:
            logger.info("Stream consumer cancelled")
            break
        except Exception:
            logger.error("Stream consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)


async def _handle_feature_event(msg_id: str, raw: dict[str, str]) -> None:
    assert _redis is not None and _ensemble is not None

    try:
        symbol = raw.get("symbol", "")
        timeframe = str(raw.get("timeframe", "")).upper()

        # Features can arrive in two formats:
        # 1. Single JSON blob under key "features"
        # 2. Flat hash keys like "features.ema_9", "features.rsi", etc.
        features_str = raw.get("features")
        if features_str is not None:
            # Format 1: nested JSON string
            if isinstance(features_str, str):
                features_dict = json.loads(features_str.replace("'", '"'))
            else:
                features_dict = features_str
        else:
            # Format 2: extract from flat "features.*" keys
            prefix = "features."
            features_dict = {}
            for k, v in raw.items():
                if k.startswith(prefix):
                    feat_name = k[len(prefix):]
                    try:
                        features_dict[feat_name] = float(v)
                    except (ValueError, TypeError):
                        features_dict[feat_name] = v  # keep strings like trend_direction

        if not features_dict:
            logger.warning("Empty features for %s — skipping event %s", symbol, msg_id)
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        # Calendar / news-surprise features — injected BEFORE prediction and
        # history accumulation so live inference and the next retrain see
        # exactly the same columns. Point-in-time: uses the bar/event
        # timestamp, never the wall clock of processing.
        try:
            prepared = await _get_prepared_calendar()
            if prepared:
                enrich_features_with_calendar(
                    symbol,
                    features_dict,
                    prepared,
                    ts_candidates=(
                        features_dict.get("timestamp"),
                        raw.get("timestamp"),
                    ),
                )
        except Exception:
            logger.debug("Calendar enrichment skipped for %s", symbol, exc_info=True)

        # Recompute dynamic TF on M5 probe bars (scalping anchor)
        if timeframe == "M5":
            try:
                from datetime import datetime, timezone

                from services.nexus_ml.traders.trading_mode import (
                    detect_session,
                    get_current_config,
                    select_operational_tf,
                )

                cfg = get_current_config()
                session = detect_session(datetime.now(timezone.utc).hour)
                spread = float(features_dict.get("spread", features_dict.get("spread_pips", 0)) or 0)
                avg_sp = float(features_dict.get("avg_spread", spread) or spread or 1.0)
                auto = True
                try:
                    from shared import runtime_settings as _rs
                    auto = bool(_rs.get_cached_settings().get("auto_tf_selection", True))
                except Exception:
                    pass
                sel = select_operational_tf(
                    cfg, session, features_dict, auto=auto,
                    current_spread=spread, avg_spread=avg_sp,
                )
                from datetime import timezone as tz
                await _redis.set(
                    "nexus:dynamic:tf",
                    json.dumps({
                        "operational_tf": sel.operational_tf,
                        "confirmation_tfs": sel.confirmation_tfs,
                        "base_tf": sel.base_tf,
                        "reason": sel.reason,
                        "vol_regime": sel.vol_regime,
                        "session": sel.session,
                        "auto_selected": sel.auto_selected,
                        "updated_at": datetime.now(tz.utc).isoformat(),
                    }),
                    ex=180,
                )
            except Exception:
                logger.debug("dynamic_tf update skipped", exc_info=True)

        # Only signal on the live operational TF to avoid triple-firing.
        operational_tf = os.getenv("NEXUS_OPERATIONAL_TF", "M5").upper()
        try:
            dyn_raw = await _redis.get("nexus:dynamic:tf")
            if dyn_raw:
                operational_tf = str(json.loads(dyn_raw).get("operational_tf", operational_tf)).upper()
        except Exception:
            pass
        if timeframe and timeframe != operational_tf:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        now = time.time()
        last = _last_signal_ts.get(symbol, 0.0)
        if last and (now - last) < SIGNAL_COOLDOWN_SEC:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        # Decide: this symbol's ML ensemble (if trained) or rule-based fallback
        ensemble = _get_symbol_ensemble(symbol)
        any_model_loaded = _has_directional_ml_model(ensemble.models_status())

        if any_model_loaded:
            # Use trained ML models for THIS symbol
            feature_array = ensemble.build_feature_array(features_dict)
            signal: EnsembleSignal = ensemble.predict(feature_array)
            signal_source = "ml_ensemble"
        elif _rule_based is not None:
            # Fallback: rule-based signal from real technical indicators
            signal = _rule_based.predict(features_dict)
            signal_source = "rule_based"
        else:
            # Should never happen — both are None
            logger.error("No signal generator available — skipping event %s", msg_id)
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        direction_map = {"BUY": Verdict.BUY, "SELL": Verdict.SELL}
        verdict = direction_map.get(signal.direction, Verdict.NO_TRADE)

        # Filter to numeric-only for SignalEvent (Pydantic expects dict[str, float])
        numeric_features = {k: v for k, v in features_dict.items() if isinstance(v, (int, float))}

        # Training target is the direction of the NEXT adjacent completed bar.
        # Keep the current bar as pending; only finalize the preceding row when
        # its next bar arrives. Raw OHLC/close and target-like keys are excluded
        # from X by sanitize_training_features(). Legacy history is not reused.
        try:
            close = features_dict.get("close")
            bar_timestamp = features_dict.get("bar_timestamp")
            if close is not None and bar_timestamp:
                current_ts = parse_utc_timestamp(bar_timestamp)
                current_pending = build_pending_sample(
                    features_dict, bar_timestamp, close,
                )
                pending_key = f"nexus:features:pending:{symbol}:{timeframe}"
                pending_raw = await _redis.get(pending_key)
                pending = json.loads(pending_raw) if pending_raw else None
                previous_ts = parse_utc_timestamp(pending.get("timestamp")) if pending else None

                # Ignore duplicate/out-of-order events; they must not relabel or
                # replace a newer pending sample.
                if current_pending and current_ts and (
                    previous_ts is None or current_ts > previous_ts
                ):
                    labeled = finalize_next_bar_sample(
                        pending, bar_timestamp, close, timeframe,
                    )
                    if labeled:
                        history_key = f"nexus:features:history:{symbol}"
                        await _redis.rpush(history_key, json.dumps(labeled))
                        await _redis.ltrim(history_key, -10000, -1)
                    await _redis.set(pending_key, json.dumps(current_pending))
        except Exception:
            logger.warning("Leakage-safe training sample accumulation failed for %s", symbol, exc_info=True)

        if verdict == Verdict.NO_TRADE:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        event = SignalEvent(
            source=ServiceName.ML,
            symbol=symbol,
            direction=verdict,
            confidence=signal.confidence,
            features=numeric_features,
            ml_scores=signal.individual_scores,
        )

        await _redis.xadd(
            RedisStream.SIGNAL_STREAM,
            event.to_stream_dict(),
            maxlen=STREAM_MAX_LEN,
        )

        _last_signal_ts[symbol] = now

        logger.info(
            "Signal published [%s]: %s %s conf=%.3f regime=%s anomaly=%s",
            signal_source, symbol, signal.direction, signal.confidence,
            signal.regime, signal.is_anomaly,
        )

    except Exception:
        logger.error("Failed to handle feature event %s", msg_id, exc_info=True)
    finally:
        await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)


# ── Helper functions ──────────────────────────────────────────────────────────


async def _get_latest_features(symbol: str) -> dict[str, float] | None:
    assert _redis is not None
    # Try common timeframes — features are cached with timeframe suffix
    for tf in ("M15", "H1", "M5", "M1"):
        cache_key = f"nexus:features:{symbol}:{tf}"
        raw = await _redis.get(cache_key)
        if raw is not None:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "features" in data:
                    return data["features"]
                return data
            except (json.JSONDecodeError, TypeError):
                continue
    return None


async def _fetch_training_data(
    symbols: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], np.ndarray] | None:
    """Fetch historical feature data from Redis/DuckDB for training.

    Returns (X, y, timestamps, feature_names) or None if no data.
    """
    assert _redis is not None

    # Calendar snapshot for point-in-time backfill on eligible v2 rows only.
    prepared_calendar = await _get_prepared_calendar()

    all_features: list[list[float]] = []
    all_labels: list[int] = []
    all_timestamps: list[str] = []
    all_target_timestamps: list[str] = []
    feature_names: list[str] = []

    for symbol in symbols:
        history_key = f"nexus:features:history:{symbol}"
        raw_list = await _redis.lrange(history_key, 0, -1)

        # Anchor the schema only to a new, versioned, finalized record. Legacy
        # rows used same-bar labels and may contain leaked prices, so skip them.
        for _raw in reversed(raw_list):
            try:
                _record = json.loads(_raw)
                if not is_eligible_training_record(_record):
                    continue
                _lf = sanitize_training_features(_record.get("features", {}))
                _lk = list(_lf)
                if _lk:
                    feature_names = _lk
                    break
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        # Guarantee the calendar columns exist in the training schema even if
        # the newest record lacked them (e.g. empty snapshot at that moment).
        for _cal in CALENDAR_FEATURE_NAMES:
            if _cal not in feature_names:
                feature_names.append(_cal)

        for raw in raw_list:
            try:
                record = json.loads(raw)
                if not is_eligible_training_record(record):
                    continue
                feats = sanitize_training_features(record.get("features", {}))
                label = record.get("label")
                ts = record.get("timestamp", "")
                target_ts = record.get("target_timestamp", "")

                if not feats or label not in (0, 1) or parse_utc_timestamp(target_ts) is None:
                    continue

                if not feature_names:
                    feature_names = list(feats.keys())

                # Backfill calendar features for records that predate the
                # ingestion-time enrichment. Point-in-time safe: computes from
                # the record's own timestamp; records without a parseable
                # timestamp keep neutral values rather than borrowing "now".
                if prepared_calendar and not has_calendar_features(feats):
                    try:
                        feats = dict(feats)
                        enrich_features_with_calendar(
                            symbol,
                            feats,
                            prepared_calendar,
                            ts_candidates=(ts,),
                            allow_now=False,
                        )
                    except Exception:
                        logger.debug(
                            "Calendar backfill failed for %s @ %s", symbol, ts,
                            exc_info=True,
                        )

                safe_feats = sanitize_training_features(feats)
                all_features.append([safe_feats.get(k, 0.0) for k in feature_names])
                all_labels.append(int(label))
                all_timestamps.append(ts)
                all_target_timestamps.append(target_ts)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    if not all_features:
        return None

    X = np.array(all_features, dtype=np.float64)
    y = np.array(all_labels, dtype=np.int64)
    timestamps = np.array([
        np.datetime64(parse_utc_timestamp(ts).replace(tzinfo=None), "s")
        for ts in all_timestamps
    ], dtype="datetime64[s]")
    target_timestamps = np.array([
        np.datetime64(parse_utc_timestamp(ts).replace(tzinfo=None), "s")
        for ts in all_target_timestamps
    ], dtype="datetime64[s]")

    # Make walk-forward input deterministic and chronological, and drop any
    # duplicate sample timestamps before fold generation.
    order = np.argsort(timestamps, kind="stable")
    X, y, timestamps, target_timestamps = X[order], y[order], timestamps[order], target_timestamps[order]
    if len(timestamps) > 1:
        keep = np.concatenate(([True], timestamps[1:] > timestamps[:-1]))
        X, y, timestamps, target_timestamps = X[keep], y[keep], timestamps[keep], target_timestamps[keep]

    return X, y, timestamps, feature_names, target_timestamps


async def _count_eligible_training_samples(symbols: list[str]) -> int:
    """Count only finalized schema-v2 rows; exclude legacy contaminated data."""
    assert _redis is not None
    total = 0
    for symbol in symbols:
        raw_list = await _redis.lrange(f"nexus:features:history:{symbol}", 0, -1)
        for raw in raw_list:
            try:
                if is_eligible_training_record(json.loads(raw)):
                    total += 1
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    return total


async def _auto_retrain_loop() -> None:
    """Background task: trigger ensemble retraining when enough new feature data accumulates.

    Checks every NEXUS_RETRAIN_CHECK_INTERVAL_SEC seconds. Skips if:
    - Less than NEXUS_RETRAIN_MIN_SAMPLES records in feature history
    - Less than NEXUS_RETRAIN_COOLDOWN_HOURS since the last retrain
    - Training is already in progress
    """
    global _training_in_progress, _ensemble

    await asyncio.sleep(60)  # Let the service fully start before first check

    while True:
        try:
            if _redis is None or _training_in_progress:
                await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)
                continue

            # Check cooldown
            last_ts_raw = await _redis.get(_RETRAIN_LAST_KEY)
            if last_ts_raw:
                elapsed_h = (time.time() - float(last_ts_raw)) / 3600
                if elapsed_h < _RETRAIN_COOLDOWN_HOURS:
                    await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)
                    continue

            # Count only finalized, versioned leakage-safe samples.
            total_samples = await _count_eligible_training_samples(_RETRAIN_SYMBOLS)

            if total_samples < _RETRAIN_MIN_SAMPLES:
                logger.info(
                    "auto_retrain.skipped samples=%d/%d",
                    total_samples, _RETRAIN_MIN_SAMPLES,
                )
                await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)
                continue

            logger.info(
                "auto_retrain.triggered samples=%d symbols=%s",
                total_samples, _RETRAIN_SYMBOLS,
            )

            import uuid
            task_id = f"auto_{uuid.uuid4().hex[:8]}"
            _training_in_progress = True

            try:
                # Auto-retraining may create candidates, never promote them.
                total_folds = 0
                candidates: dict[str, str] = {}
                for sym in _RETRAIN_SYMBOLS:
                    data = await _fetch_training_data([sym])
                    if data is None:
                        logger.warning("auto_retrain.no_data symbol=%s", sym)
                        continue

                    out_dir = candidate_model_dir(task_id, sym)
                    out_dir.mkdir(parents=True, exist_ok=True)

                    X, y, timestamps, feature_names, target_timestamps = data
                    cfg = WalkForwardConfig(
                        train_months=6,
                        val_months=1,
                        step_months=2,
                        model_dir=str(out_dir),
                    )
                    trainer = WalkForwardTrainer(cfg)
                    results = trainer.train_all_models(
                        X, y, timestamps, feature_names, target_timestamps=target_timestamps,
                    )
                    total_folds += len(results)
                    if results:
                        _write_candidate_receipt(task_id, sym, len(results), source="redis_live_history")
                        candidates[sym] = str(out_dir)
                    logger.info("auto_retrain.candidate_done symbol=%s folds=%d path=%s", sym, len(results), out_dir)

                logger.info("auto_retrain.complete folds=%d task=%s", total_folds, task_id)
                await _redis.set(_RETRAIN_LAST_KEY, str(time.time()), ex=86_400 * 7)

                # Publish retrain event to Redis for dashboard visibility
                try:
                    await _redis.set(
                        "nexus:ml:last_retrain_result",
                        json.dumps({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "samples": int(total_samples),
                            "folds": total_folds,
                            "candidate_id": task_id,
                            "candidates": candidates,
                            "champion_unchanged": True,
                        }),
                        ex=86_400 * 2,
                    )
                except Exception:
                    pass

            finally:
                _training_in_progress = False

        except asyncio.CancelledError:
            break
        except Exception:
            logger.error("auto_retrain.error", exc_info=True)

        await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)


async def _heartbeat_loop() -> None:
    assert _redis is not None
    while True:
        try:
            from shared.events import SystemHealthEvent
            import psutil

            event = SystemHealthEvent(
                source=ServiceName.ML,
                service_name=ServiceName.ML,
                status="healthy",
                cpu_pct=psutil.cpu_percent(),
                ram_pct=psutil.virtual_memory().percent,
            )
            await _redis.xadd(
                RedisStream.SYSTEM_HEALTH_STREAM,
                event.to_stream_dict(),
                maxlen=STREAM_MAX_LEN,
            )
        except Exception:
            logger.debug("Heartbeat failed", exc_info=True)

        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.nexus_ml.main:app",
        host="0.0.0.0",
        port=8003,
        reload=False,
        log_level="info",
    )
