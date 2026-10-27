"""
Tests for calendar / news-surprise ML features.

Covers value parsing, surprise normalisation, point-in-time windowing
(no future leakage), currency relevance mapping, and enrichment idempotence
— the contract shared by training backfill and live inference.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from services.nexus_ml.calendar_features import (
    CALENDAR_FEATURE_NAMES,
    _to_float,
    compute_calendar_features,
    compute_surprise,
    enrich_features_with_calendar,
    has_calendar_features,
    prepare_events,
    resolve_currencies,
)

UTC = timezone.utc


def _ev(
    time: str,
    currency: str = "USD",
    importance: str = "high",
    actual=None,
    forecast=None,
    previous=None,
    name: str = "Test Event",
) -> dict:
    return {
        "event_id": name,
        "name": name,
        "currency": currency,
        "importance": importance,
        "time": time,
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
    }


class TestValueParsing:
    def test_plain_number(self):
        assert _to_float("90.4") == 90.4

    def test_percent(self):
        assert _to_float("0.7%") == 0.7

    def test_thousands_suffix(self):
        assert _to_float("0.708M") == 708_000.0
        assert _to_float("-2.067M") == pytest.approx(-2_067_000.0)
        assert _to_float("1.2K") == 1_200.0

    def test_comma_thousands(self):
        assert _to_float("1,234.5") == 1234.5

    def test_null_and_garbage(self):
        assert _to_float(None) is None
        assert _to_float("") is None
        assert _to_float("N/A") is None
        assert _to_float("—") is None
        assert _to_float("nonsense") is None

    def test_numeric_passthrough(self):
        assert _to_float(4.5) == 4.5
        assert _to_float(-3) == -3.0


class TestSurprise:
    def test_basic_surprise(self):
        # (1.2 - 0.7) / max(0.7, 0.0) = 0.714
        ev = _ev("2026-10-27T12:30:00Z", actual="1.2%", forecast="0.7%", previous="0.0%")
        assert compute_surprise(ev) == pytest.approx(0.714, abs=1e-3)

    def test_below_forecast_negative(self):
        ev = _ev("2026-10-27T12:30:00Z", actual="0.4", forecast="0.5", previous="0.4")
        assert compute_surprise(ev) == pytest.approx(-0.2, abs=1e-9)

    def test_forecast_missing_uses_previous_baseline(self):
        # Fed Interest Rate Decision pattern: forecast None, previous 4.00%
        ev = _ev("2026-10-28T18:00:00Z", actual="3.75%", forecast=None, previous="4.00%")
        assert compute_surprise(ev) == pytest.approx(-0.0625, abs=1e-4)

    def test_zero_reference_is_zero_not_inf(self):
        ev = _ev("2026-10-27T12:30:00Z", actual="0.2%", forecast="0.0%", previous="0.0%")
        assert compute_surprise(ev) == 0.0

    def test_missing_actual_is_none(self):
        ev = _ev("2026-10-27T12:30:00Z", forecast="0.7%", previous="0.0%")
        assert compute_surprise(ev) is None

    def test_clip_to_three(self):
        ev = _ev("2026-10-27T12:30:00Z", actual="10.0", forecast="0.1", previous="0.1")
        assert compute_surprise(ev) == 3.0
        ev2 = _ev("2026-10-27T12:30:00Z", actual="-10.0", forecast="0.1", previous="0.1")
        assert compute_surprise(ev2) == -3.0

    def test_index_level_small_diff(self):
        # JP Coincident Index real sample: 118.8 vs 118.7
        ev = _ev("2026-10-26T05:00:00Z", importance="low", actual="118.8", forecast="118.7", previous="118.7")
        assert compute_surprise(ev) == pytest.approx(0.1 / 118.7, abs=1e-9)


class TestCurrencyResolution:
    def test_override_xauusd(self):
        assert resolve_currencies("XAUUSD", {"USD", "EUR", "JPY"}) == ["USD"]

    def test_chunk_split_eurusd(self):
        assert resolve_currencies("EURUSD", {"USD", "EUR", "JPY"}) == ["EUR", "USD"]

    def test_unknown_symbol_falls_back_to_usd(self):
        assert resolve_currencies("WEIRD7", {"USD", "EUR"}) == ["USD"]

    def test_case_insensitive(self):
        assert resolve_currencies("xauusd", {"usd"}) == ["USD"]


class TestPointInTimeWindows:
    """No future leakage: forward features use events strictly after ts."""

    def setup_method(self):
        self.ts = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

    def test_no_events_neutral(self):
        feats = compute_calendar_features("XAUUSD", self.ts, [])
        assert feats["cal_proximity_high"] == 0.0
        assert feats["cal_min_to_next_high"] == 1440.0
        assert feats["cal_high_last90"] == 0.0
        assert feats["cal_surprise_signed"] == 0.0
        assert feats["cal_high_count_next24h"] == 0.0

    def test_proximity_decay_30min(self):
        events = prepare_events([_ev("2026-10-27T12:30:00Z")])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_min_to_next_high"] == pytest.approx(30.0)
        assert feats["cal_proximity_high"] == pytest.approx(math.exp(-30 / 45))

    def test_event_beyond_horizon_is_invisible(self):
        # 25 h ahead: outside the 24 h forward horizon entirely
        events = prepare_events([_ev("2026-10-28T13:00:00Z")])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_proximity_high"] == 0.0
        assert feats["cal_min_to_next_high"] == 1440.0
        assert feats["cal_high_count_next24h"] == 0.0

    def test_high_last90_within_and_outside(self):
        within = prepare_events([_ev("2026-10-27T11:00:00Z")])   # 60 min ago
        feats = compute_calendar_features("XAUUSD", self.ts, within)
        assert feats["cal_high_last90"] == 1.0

        outside = prepare_events([_ev("2026-10-27T10:00:00Z")])  # 120 min ago
        feats = compute_calendar_features("XAUUSD", self.ts, outside)
        assert feats["cal_high_last90"] == 0.0

    def test_surprise_window_240min(self):
        inside = prepare_events([
            _ev("2026-10-27T08:40:00Z", actual="1.2%", forecast="0.7%"),  # 200 min ago
        ])
        feats = compute_calendar_features("XAUUSD", self.ts, inside)
        assert feats["cal_surprise_signed"] != 0.0

        outside = prepare_events([
            _ev("2026-10-27T07:00:00Z", actual="1.2%", forecast="0.7%"),  # 300 min ago
        ])
        feats = compute_calendar_features("XAUUSD", self.ts, outside)
        assert feats["cal_surprise_signed"] == 0.0

    def test_most_recent_surprise_wins(self):
        events = prepare_events([
            _ev("2026-10-27T09:00:00Z", name="Older", actual="1.0", forecast="0.5"),
            _ev("2026-10-27T11:30:00Z", name="Newer", actual="0.6", forecast="0.5"),
        ])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_surprise_signed"] == pytest.approx(0.2, abs=1e-9)

    def test_no_leakage_future_event_not_surprise(self):
        # Event 10 min in the FUTURE must not feed surprise / high_last90…
        events = prepare_events([_ev("2026-10-27T12:10:00Z", actual="5.0", forecast="0.5")])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_surprise_signed"] == 0.0
        assert feats["cal_high_last90"] == 0.0
        # …but must feed forward features.
        assert feats["cal_min_to_next_high"] == pytest.approx(10.0)

    def test_no_leakage_past_event_not_proximity(self):
        # Event 10 min in the PAST must not feed forward features…
        events = prepare_events([_ev("2026-10-27T11:50:00Z")])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_min_to_next_high"] == 1440.0
        assert feats["cal_proximity_high"] == 0.0
        # …but must feed the post-news flag.
        assert feats["cal_high_last90"] == 1.0

    def test_currency_filter_eur_ignored_for_gold(self):
        events = prepare_events([
            _ev("2026-10-27T12:30:00Z", currency="EUR", name="EUR Event"),
        ])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_min_to_next_high"] == 1440.0
        # Same event counts for EURUSD.
        feats_eur = compute_calendar_features("EURUSD", self.ts, events)
        assert feats_eur["cal_min_to_next_high"] == pytest.approx(30.0)

    def test_medium_impact_surprise_counts_low_does_not(self):
        medium = prepare_events([
            _ev("2026-10-27T11:00:00Z", importance="medium", actual="1.2", forecast="1.0"),
        ])
        assert compute_calendar_features("XAUUSD", self.ts, medium)["cal_surprise_signed"] != 0.0

        low = prepare_events([
            _ev("2026-10-27T11:00:00Z", importance="low", actual="1.2", forecast="1.0"),
        ])
        assert compute_calendar_features("XAUUSD", self.ts, low)["cal_surprise_signed"] == 0.0

    def test_count_next24h_multiple(self):
        events = prepare_events([
            _ev("2026-10-27T13:00:00Z", name="A"),
            _ev("2026-10-27T15:00:00Z", name="B"),
            _ev("2026-10-27T20:00:00Z", name="C"),
            _ev("2026-10-27T15:00:00Z", currency="EUR", name="D"),  # not USD
        ])
        feats = compute_calendar_features("XAUUSD", self.ts, events)
        assert feats["cal_high_count_next24h"] == 3.0
        assert feats["cal_min_to_next_high"] == pytest.approx(60.0)


class TestEnrichment:
    def test_enrich_adds_all_six(self):
        events = prepare_events([_ev("2026-10-27T12:30:00Z")])
        feats: dict = {"close": 4000.0}
        changed = enrich_features_with_calendar(
            "XAUUSD", feats, events,
            ts_candidates=("2026-10-27T12:00:00Z",),
        )
        assert changed is True
        assert all(name in feats for name in CALENDAR_FEATURE_NAMES)
        assert feats["cal_min_to_next_high"] == pytest.approx(30.0)

    def test_enrich_idempotent(self):
        events = prepare_events([_ev("2026-10-27T12:30:00Z")])
        feats: dict = {"close": 4000.0, "cal_proximity_high": 0.42}
        changed = enrich_features_with_calendar(
            "XAUUSD", feats, events, ts_candidates=("2026-10-27T12:00:00Z",),
        )
        assert changed is False
        assert feats["cal_proximity_high"] == 0.42  # point-in-time value kept

    def test_backfill_no_timestamp_no_fabrication(self):
        events = prepare_events([_ev("2026-10-27T12:30:00Z")])
        feats: dict = {"close": 4000.0}
        changed = enrich_features_with_calendar(
            "XAUUSD", feats, events, ts_candidates=("", None), allow_now=False,
        )
        assert changed is False
        assert not has_calendar_features(feats)

    def test_backfill_with_timestamp_uses_it(self):
        events = prepare_events([_ev("2026-10-27T12:30:00Z")])
        feats: dict = {"close": 4000.0}
        changed = enrich_features_with_calendar(
            "XAUUSD", feats, events,
            ts_candidates=("2026-10-27T12:25:00Z",), allow_now=False,
        )
        assert changed is True
        assert feats["cal_min_to_next_high"] == pytest.approx(5.0)

    def test_fallback_to_second_candidate(self):
        events = prepare_events([_ev("2026-10-27T12:30:00Z")])
        feats: dict = {"close": 4000.0}
        enrich_features_with_calendar(
            "XAUUSD", feats, events,
            ts_candidates=(None, "2026-10-27T12:15:00Z"),
        )
        assert feats["cal_min_to_next_high"] == pytest.approx(15.0)
