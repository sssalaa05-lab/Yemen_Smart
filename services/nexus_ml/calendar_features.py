"""
Calendar / news-surprise features for ML training and live inference.

Turns the MT5 economic calendar snapshot (Redis key ``nexus:calendar:mt5``,
published every 5 minutes by NexusCalendarEA -> bridge.py -> nexus-data) into
numeric features aligned to each M5 bar timestamp:

  cal_proximity_high      exp-decay proximity (tau = 45 min) to the nearest
                          upcoming high-impact event for the symbol's
                          relevant currencies; 0 when none within 24 h.
  cal_min_to_next_high    minutes to the next high-impact event, capped at
                          [0, 1440]; 1440 means "none within the horizon".
  cal_high_last90         1 if a high-impact event for the relevant
                          currencies was released within the last 90 minutes
                          (post-news volatility window).
  cal_surprise_signed     normalised surprise (actual - forecast) / ref of the
                          most recent released high/medium-impact event that
                          carries both values, within the last 240 minutes.
                          Clipped to [-3, +3]; 0 when no surprise available.
  cal_surprise_abs        |cal_surprise_signed|.
  cal_high_count_next24h  number of high-impact events in the next 24 hours.

Design notes
------------
* Point-in-time safe: for a bar at time T only events with ``time <= T``
  feed the surprise / post-news flags, and only events with ``time > T``
  feed the forward-looking ones (proximity / countdown / count). A bar can
  never see an event that had not happened yet.
* All features degrade to neutral values when the calendar snapshot is
  missing or does not cover the timestamp — never NaN / inf.
* Surprise normalisation: reference = max(|forecast|, |previous|) so a zero
  forecast cannot explode the ratio; the ratio is clipped to ±3. Events
  whose reference is ~0 (e.g. "0.0% vs 0.0%") yield 0 (indeterminate, not
  infinite).
* Event values arrive as human strings from the EA ("0.7%", "0.708M",
  "-2.067M", "118.7") — ``_to_float`` strips % , commas and K/M/B/T
  suffixes before arithmetic.
* Currency relevance is derived from the symbol: explicit overrides first
  (XAUUSD -> USD), then a generic 3-letter chunk split intersected with the
  currencies actually present in the calendar, falling back to USD.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# ── Public constants ──────────────────────────────────────────────────────────

CALENDAR_FEATURE_NAMES: list[str] = [
    "cal_proximity_high",
    "cal_min_to_next_high",
    "cal_high_last90",
    "cal_surprise_signed",
    "cal_surprise_abs",
    "cal_high_count_next24h",
]

# Neutral values returned when there is no usable calendar coverage.
_NEUTRAL: dict[str, float] = {
    "cal_proximity_high": 0.0,
    "cal_min_to_next_high": 1440.0,
    "cal_high_last90": 0.0,
    "cal_surprise_signed": 0.0,
    "cal_surprise_abs": 0.0,
    "cal_high_count_next24h": 0.0,
}

# Symbols whose name does not decompose into calendar currencies.
SYMBOL_CURRENCY_OVERRIDES: dict[str, list[str]] = {
    "XAUUSD": ["USD"],
    "XAGUSD": ["USD"],
    "BTCUSD": ["USD"],
    "ETHUSD": ["USD"],
    "US30": ["USD"],
    "NAS100": ["USD"],
    "SPX500": ["USD"],
    "USOIL": ["USD", "CAD"],
    "UKOIL": ["USD"],
    "GER40": ["EUR"],
    "JP225": ["JPY"],
}

# Window / decay parameters (minutes unless noted).
_PROXIMITY_TAU_MIN = 45.0        # exp decay constant for proximity
_FORWARD_HORIZON_MIN = 1440.0    # 24 h lookahead for proximity / countdown
_SURPRISE_LOOKBACK_MIN = 240.0   # surprise valid for 4 h after release
_HIGH_FLAG_LOOKBACK_MIN = 90.0   # post-news volatility window
_SURPRISE_CLIP = 3.0
_UNIT_MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


# ── Parsing helpers ───────────────────────────────────────────────────────────


def _parse_iso(value: Any) -> datetime | None:
    """Parse ISO-8601 timestamps ('...Z', '+00:00' or naive) to aware UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_float(value: Any) -> float | None:
    """Parse EA calendar strings: '90.4', '0.7%', '0.708M', '-2.067M', '1,234'.

    Returns None for null / unparseable values (LONG_MIN sentinels are already
    converted to JSON null upstream by EA v1.02).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "null", "None"}:
        return None
    try:
        mult = 1.0
        if text and text[-1].upper() in _UNIT_MULTIPLIERS:
            # Only treat as unit suffix when the rest parses as a number
            # (avoids mangling plain numbers that happen to end in K/M…).
            mult = _UNIT_MULTIPLIERS[text[-1].upper()]
            text = text[:-1]
        if text.endswith("%"):
            text = text[:-1]
        parsed = float(text)
    except ValueError:
        return None
    return parsed * mult


def compute_surprise(event: dict[str, Any]) -> float | None:
    """Normalised surprise (actual - baseline) / ref, clipped to ±3.

    baseline = forecast when present, else previous.
    ref      = max(|forecast|, |previous|) — guards against division by ~0.
    """
    actual = _to_float(event.get("actual"))
    if actual is None:
        return None
    forecast = _to_float(event.get("forecast"))
    previous = _to_float(event.get("previous"))

    candidates = [abs(v) for v in (forecast, previous) if v is not None]
    ref = max(candidates) if candidates else None
    if ref is None or ref < 1e-12:
        # Forecast and previous both ~0 (or absent): direction is undefined.
        return 0.0

    baseline = forecast if forecast is not None else previous
    if baseline is None:
        return None

    surprise = (actual - baseline) / ref
    return max(-_SURPRISE_CLIP, min(_SURPRISE_CLIP, surprise))


# ── Currency relevance ────────────────────────────────────────────────────────


def resolve_currencies(
    symbol: str, calendar_currencies: Iterable[str] | None = None,
) -> list[str]:
    """Map a trading symbol to the calendar currencies that move it.

    Order: explicit override -> 3-letter chunk intersection with the
    calendar's currency set -> ['USD'] fallback.
    """
    sym = (symbol or "").strip().upper()
    if sym in SYMBOL_CURRENCY_OVERRIDES:
        return list(SYMBOL_CURRENCY_OVERRIDES[sym])

    known = {c.upper() for c in calendar_currencies or [] if c}
    chunks = [sym[i : i + 3] for i in range(0, max(len(sym) - 2, 0), 3)]
    hits = [c for c in chunks if c in known]
    if hits:
        return hits
    return ["USD"]


# ── Event preparation ─────────────────────────────────────────────────────────


def prepare_events(events: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalise raw calendar events into a sorted, pre-parsed list.

    Each prepared event: {dt, currency, importance, surprise}. Events without
    a parseable time or currency are dropped. Output is sorted ascending by
    time so scans can short-circuit and 'most recent' resolution is stable.
    """
    prepared: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        dt = _parse_iso(ev.get("time") or ev.get("timestamp"))
        if dt is None:
            continue
        currency = str(ev.get("currency") or ev.get("country") or "").upper()
        if not currency:
            continue
        available_at = _parse_iso(ev.get("available_at"))
        # Fail closed: an event timestamp is not evidence that its forecast,
        # actual, or revised values were already published at that time.
        if available_at is None:
            continue
        prepared.append({
            "dt": dt,
            "available_at": available_at,
            "revision_id": str(ev.get("revision_id") or ev.get("revision") or ""),
            "event_id": str(ev.get("event_id") or ev.get("id") or ""),
            "currency": currency,
            "importance": str(ev.get("importance") or "low").lower(),
            "surprise": compute_surprise(ev),
        })
    prepared.sort(key=lambda e: e["dt"])
    return prepared


# ── Feature computation ───────────────────────────────────────────────────────


def resolve_bar_timestamp(*candidates: Any) -> datetime:
    """First parseable timestamp among candidates, else now (UTC)."""
    for cand in candidates:
        dt = cand if isinstance(cand, datetime) else _parse_iso(cand)
        if dt is not None:
            return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def compute_calendar_features(
    symbol: str,
    ts: datetime,
    prepared_events: list[dict[str, Any]] | None,
    currencies: list[str] | None = None,
) -> dict[str, float]:
    """Compute the 6 calendar features for one bar timestamp.

    ``ts`` must be the bar's point-in-time (aware UTC datetime). Forward
    features look strictly after ``ts``; surprise / post-news flags look
    strictly at or before ``ts``.
    """
    features = dict(_NEUTRAL)
    if not prepared_events:
        return features

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)

    rel = set(currencies) if currencies else set(
        resolve_currencies(symbol, {e["currency"] for e in prepared_events})
    )
    if not rel:
        return features

    next_high_sec: float | None = None
    count_next24h = 0
    high_in_window = False
    surprise: float | None = None
    surprise_dt: datetime | None = None

    # If revisions coexist in an archival source, use only the latest version
    # that was actually available by decision time. Counting every vintage
    # would double-count events and could expose a later correction.
    latest_by_event: dict[str, dict[str, Any]] = {}
    for index, ev in enumerate(prepared_events):
        if ev["available_at"] > ts:
            continue
        event_key = ev.get("event_id") or f"__row_{index}"
        prior = latest_by_event.get(event_key)
        if prior is None or ev["available_at"] > prior["available_at"]:
            latest_by_event[event_key] = ev

    for ev in latest_by_event.values():
        if ev["currency"] not in rel:
            continue
        delta_sec = (ev["dt"] - ts).total_seconds()

        if delta_sec > 0:
            # ── future event (relative to the bar) ──
            if ev["importance"] != "high":
                continue
            if delta_sec <= _FORWARD_HORIZON_MIN * 60:
                count_next24h += 1
                if next_high_sec is None or delta_sec < next_high_sec:
                    next_high_sec = delta_sec
        else:
            # ── released at or before the bar ──
            age_min = -delta_sec / 60.0
            if ev["importance"] == "high" and age_min <= _HIGH_FLAG_LOOKBACK_MIN:
                high_in_window = True
            if (
                ev["importance"] in ("high", "medium")
                and age_min <= _SURPRISE_LOOKBACK_MIN
                and ev["surprise"] is not None
                and (surprise_dt is None or ev["dt"] > surprise_dt)
            ):
                surprise_dt = ev["dt"]
                surprise = ev["surprise"]

    if next_high_sec is not None:
        minutes = next_high_sec / 60.0
        features["cal_min_to_next_high"] = min(minutes, _FORWARD_HORIZON_MIN)
        features["cal_proximity_high"] = math.exp(-minutes / _PROXIMITY_TAU_MIN)
    features["cal_high_last90"] = 1.0 if high_in_window else 0.0
    features["cal_high_count_next24h"] = float(count_next24h)
    if surprise is not None:
        features["cal_surprise_signed"] = surprise
        features["cal_surprise_abs"] = abs(surprise)
    return features


def has_calendar_features(features: dict[str, Any]) -> bool:
    """True when the dict already carries calendar features (idempotence)."""
    return any(name in features for name in CALENDAR_FEATURE_NAMES)


def enrich_features_with_calendar(
    symbol: str,
    features: dict[str, Any],
    prepared_events: list[dict[str, Any]] | None,
    ts_candidates: tuple[Any, ...] = (),
    allow_now: bool = True,
) -> bool:
    """Inject the 6 calendar features into ``features`` in place.

    Timestamp resolution order: first parseable entry of ``ts_candidates``
    (bar timestamp / event arrival time), else now — unless ``allow_now`` is
    False (used for historical backfill, where "now" would fabricate
    point-in-time values for records without a parseable timestamp).

    Returns True when features were added. Idempotent: dicts that already
    carry calendar features are left untouched so point-in-time values
    written at ingestion always win over recomputation.
    """
    if has_calendar_features(features):
        return False
    ts = resolve_bar_timestamp(*ts_candidates)
    if not allow_now and not any(
        (isinstance(c, datetime) and c.tzinfo is not None) or _parse_iso(c)
        for c in ts_candidates
    ):
        return False
    features.update(compute_calendar_features(symbol, ts, prepared_events))
    as_of = [ev for ev in (prepared_events or []) if ev["available_at"] <= ts]
    revisions = sorted({
        (str(ev.get("event_id") or ""), str(ev.get("revision_id") or ""), ev["available_at"].isoformat())
        for ev in as_of
    })
    features["_calendar_provenance"] = {
        "decision_time": ts.isoformat(),
        "availability_policy": "available_at<=decision_time; latest_revision_per_event",
        "event_revisions": [
            {"event_id": event_id, "revision_id": revision_id, "available_at": available_at}
            for event_id, revision_id, available_at in revisions
        ],
    }
    return True
