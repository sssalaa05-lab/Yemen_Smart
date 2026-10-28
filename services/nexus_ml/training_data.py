"""Leakage-safe feature and next-bar label helpers for historical training."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

TRAINING_SCHEMA_VERSION = 2
LABEL_DEFINITION = "next_observed_adjacent_bar_close_direction"

_RAW_OR_META_FEATURES = {
    "open", "high", "low", "close", "volume", "tick_volume", "real_volume",
    "spread", "timestamp", "bar_timestamp", "symbol", "timeframe", "label",
    "target", "y", "ohlcv", "open_time", "close_time",
}
_UNSAFE_NAME_PARTS = (
    "label", "target", "future", "forward", "outcome", "next_close",
    "next_open", "next_high", "next_low", "next_return", "lead_",
)
_PIT_FEATURE_PREFIXES: dict[str, tuple[str, ...]] = {
    "cross_asset": ("dxy_", "us10y_", "gold_dxy_", "gold_yield_", "corr_gold_dxy_", "cross_asset_"),
    "news": ("news_", "headline_"),
    "sentiment": ("sentiment_", "social_"),
    "macro": ("macro_", "economic_", "fundamental_"),
}

_TIMEFRAME_SECONDS = {
    "M1": 60, "M2": 120, "M3": 180, "M4": 240, "M5": 300,
    "M6": 360, "M10": 600, "M12": 720, "M15": 900, "M20": 1200,
    "M30": 1800, "H1": 3600, "H2": 7200, "H3": 10800,
    "H4": 14400, "H6": 21600, "H8": 28800, "H12": 43200,
    "D1": 86400, "W1": 604800,
}


def parse_utc_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp as UTC; reject missing or malformed values."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def sanitize_training_features(features: dict[str, Any]) -> dict[str, float]:
    """Keep finite numeric predictors and drop raw prices, metadata and targets."""
    safe: dict[str, float] = {}
    for raw_name, raw_value in features.items():
        name = str(raw_name).strip().lower()
        compact_name = re.sub(r"[^a-z0-9_]+", "_", name)
        if not is_safe_feature_name(compact_name):
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            continue
        value = float(raw_value)
        if math.isfinite(value):
            safe[str(raw_name)] = value
    return safe


def is_safe_feature_name(name: str) -> bool:
    """Return whether a feature name is not raw target/price/meta information."""
    compact_name = re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower())
    if not compact_name or compact_name in _RAW_OR_META_FEATURES:
        return False
    if any(part in compact_name for part in _UNSAFE_NAME_PARTS):
        return False
    if compact_name.endswith("_price") or compact_name.startswith("price_"):
        return False
    return True


def training_schema_is_safe(schema: Any) -> bool:
    """Require an explicit v2 schema receipt before loading persisted models."""
    return (
        isinstance(schema, dict)
        and schema.get("schema_version") == TRAINING_SCHEMA_VERSION
        and schema.get("label_definition") == LABEL_DEFINITION
        and isinstance(schema.get("trained_models"), list)
        and bool(schema["trained_models"])
        and isinstance(schema.get("feature_names"), list)
        and bool(schema["feature_names"])
        and all(is_safe_feature_name(name) for name in schema["feature_names"])
    )


def purge_boundary_sample(train_mask: Any) -> Any:
    """Embargo the final training sample in a bool mask or integer index list."""
    import numpy as np

    values = np.asarray(train_mask)
    if values.dtype == bool:
        purged = values.copy()
        indices = np.flatnonzero(purged)
        if len(indices):
            purged[indices[-1]] = False
        return purged
    # Compact fallback fold generator returns integer row indices, not a mask.
    return values[:-1].copy() if len(values) else values.copy()


def purge_overlapping_targets(
    train_mask: Any,
    validation_mask: Any,
    sample_timestamps: Any,
    target_timestamps: Any,
    *,
    gap: Any = 0,
) -> Any:
    """Purge training labels whose information horizon reaches validation.

    ``target_timestamps[i]`` is when row i's forward outcome becomes known.
    A training row is excluded when its target time is on/after the first
    validation decision time minus ``gap``. Works with numpy datetime arrays
    or aware Python datetime sequences. This is independent of the current
    next-adjacent-bar label and remains valid when a longer target is added.
    """
    import numpy as np

    train = np.asarray(train_mask)
    val = np.asarray(validation_mask)
    samples = np.asarray(sample_timestamps, dtype="datetime64[ns]")
    targets = np.asarray(target_timestamps, dtype="datetime64[ns]")
    if train.dtype != bool or val.dtype != bool:
        raise ValueError("train_mask and validation_mask must be boolean masks")
    if not (len(train) == len(val) == len(samples) == len(targets)):
        raise ValueError("masks and timestamps must have identical lengths")
    if np.any(train & val):
        raise ValueError("train and validation masks must not overlap")
    val_indices = np.flatnonzero(val)
    if not len(val_indices):
        return train.copy()
    boundary = np.min(samples[val_indices]) - np.asarray(gap, dtype="timedelta64[ns]")
    keep = train.copy()
    keep &= targets < boundary
    return keep


def build_pending_sample(
    features: dict[str, Any], timestamp: Any, close: Any,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build an unlabeled, point-in-time sample from one completed bar."""
    parsed_ts = parse_utc_timestamp(timestamp)
    safe_features = sanitize_training_features(features)
    try:
        close_value = float(close)
    except (TypeError, ValueError):
        return None
    if parsed_ts is None or not math.isfinite(close_value) or close_value <= 0 or not safe_features:
        return None
    feature_provenance = features.get("_calendar_provenance")
    external_provenance = provenance or features.get("_external_provenance")
    if external_provenance:
        feature_provenance = {
            "calendar": feature_provenance,
            "external_sources": external_provenance,
        }
    return {
        "timestamp": parsed_ts.isoformat(),
        "close": close_value,
        "features": safe_features,
        "feature_provenance": feature_provenance,
    }


def finalize_next_bar_sample(
    pending: dict[str, Any] | None,
    current_timestamp: Any,
    current_close: Any,
    timeframe: str,
) -> dict[str, Any] | None:
    """Label pending features only when the immediately adjacent bar arrives.

    Returns a versioned training record, or None for invalid, duplicate,
    out-of-order, non-adjacent, or flat-price observations.
    """
    if not pending:
        return None
    previous_ts = parse_utc_timestamp(pending.get("timestamp"))
    current_ts = parse_utc_timestamp(current_timestamp)
    duration = _TIMEFRAME_SECONDS.get(str(timeframe).upper())
    if previous_ts is None or current_ts is None or duration is None:
        return None
    if (current_ts - previous_ts).total_seconds() != duration:
        return None
    try:
        previous_close = float(pending["close"])
        next_close = float(current_close)
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(previous_close) or not math.isfinite(next_close):
        return None
    if previous_close <= 0 or next_close <= 0 or next_close == previous_close:
        return None
    features = sanitize_training_features(pending.get("features", {}))
    if not features:
        return None
    return {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "label_definition": LABEL_DEFINITION,
        "timeframe": str(timeframe).upper(),
        "features": features,
        "label": int(next_close > previous_close),
        "timestamp": previous_ts.isoformat(),
        "target_timestamp": current_ts.isoformat(),
        "feature_provenance": pending.get("feature_provenance"),
    }


def is_eligible_training_record(record: Any) -> bool:
    """Reject legacy records whose label/features cannot be proven leakage-safe."""
    if not isinstance(record, dict):
        return False
    if record.get("schema_version") != TRAINING_SCHEMA_VERSION:
        return False
    if record.get("label_definition") != LABEL_DEFINITION:
        return False
    if record.get("label") not in (0, 1):
        return False
    sample_ts = parse_utc_timestamp(record.get("timestamp"))
    target_ts = parse_utc_timestamp(record.get("target_timestamp"))
    if sample_ts is None or target_ts is None or target_ts <= sample_ts:
        return False
    raw_features = record.get("features", {})
    if not isinstance(raw_features, dict):
        return False
    safe_features = sanitize_training_features(raw_features)
    # Versioned rows must already conform to the contract; do not silently
    # accept contaminated records merely because a later loader could strip keys.
    if not safe_features or set(raw_features) != set(safe_features):
        return False
    provenance = record.get("feature_provenance")
    if any(name.startswith("cal_") for name in raw_features):
        calendar_provenance = provenance.get("calendar", provenance) if isinstance(provenance, dict) else None
        if not isinstance(calendar_provenance, dict):
            return False
        decision_ts = parse_utc_timestamp(calendar_provenance.get("decision_time"))
        if decision_ts != sample_ts:
            return False
        if calendar_provenance.get("availability_policy") != "available_at<=decision_time; latest_revision_per_event":
            return False
        revisions = calendar_provenance.get("event_revisions")
        if not isinstance(revisions, list):
            return False
        for revision in revisions:
            if not isinstance(revision, dict):
                return False
            available = parse_utc_timestamp(revision.get("available_at"))
            if available is None or available > sample_ts:
                return False
    required_sources = {
        source for source, prefixes in _PIT_FEATURE_PREFIXES.items()
        if any(name.lower().startswith(prefix) for name in raw_features for prefix in prefixes)
    }
    if required_sources:
        external_sources = provenance.get("external_sources") if isinstance(provenance, dict) else None
        if not isinstance(external_sources, dict):
            return False
        for source in required_sources:
            receipt = external_sources.get(source)
            if not isinstance(receipt, dict):
                return False
            decision_ts = parse_utc_timestamp(receipt.get("decision_time"))
            if decision_ts != sample_ts:
                return False
            policy = receipt.get("availability_policy", "")
            if not isinstance(policy, str) or not policy.startswith("available_at<=decision_time;"):
                return False
            revisions = receipt.get("revisions")
            if not isinstance(revisions, list) or not revisions:
                return False
            for revision in revisions:
                if not isinstance(revision, dict):
                    return False
                available = parse_utc_timestamp(revision.get("available_at"))
                revision_id = revision.get("revision_id")
                source_id = revision.get("source_id") or revision.get("series_id") or revision.get("event_id")
                if available is None or available > sample_ts or not revision_id or not source_id:
                    return False
    return True
