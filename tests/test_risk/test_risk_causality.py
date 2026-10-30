from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.nexus_risk.position_sizer import PositionSizer
from services.nexus_risk.rules_engine import RulesEngine
from shared.models import TradeProposal, Verdict

UTC = timezone.utc


def test_position_size_is_monotone_in_stop_distance_and_balance() -> None:
    sizer = PositionSizer(max_lots=1.0, min_lot_step=0.01)

    base = sizer.calculate_size(10_000, 1.0, 2_000, 1_000, "low", "normal", "london")
    wider_stop = sizer.calculate_size(10_000, 1.0, 2_000, 0, "low", "normal", "london")
    lower_balance = sizer.calculate_size(5_000, 1.0, 2_000, 1_000, "low", "normal", "london")

    assert base.lots > wider_stop.lots > 0
    assert lower_balance.lots < base.lots
    assert base.lots <= sizer.max_allowed_lots(10_000)
    assert lower_balance.lots <= sizer.max_allowed_lots(5_000)


def test_position_sizer_fails_closed_for_invalid_or_non_finite_inputs() -> None:
    sizer = PositionSizer()
    for kwargs in (
        {"balance": 0, "risk_pct": 1, "entry": 100, "sl": 90},
        {"balance": 10_000, "risk_pct": -1, "entry": 100, "sl": 90},
        {"balance": 10_000, "risk_pct": 1, "entry": float("nan"), "sl": 90},
        {"balance": 10_000, "risk_pct": 1, "entry": 100, "sl": 100},
    ):
        result = sizer.calculate_size(**kwargs)
        assert result.lots == 0.0
        assert result.capped is True
        assert result.reason


def test_news_blackout_uses_explicit_historical_decision_time() -> None:
    engine = RulesEngine()
    engine.set_upcoming_news([
        {"timestamp": "2026-10-26T06:03:00Z", "impact": "high"},
    ])

    before = engine.check_news_blackout("2026-10-26T09:00:00+03:00")
    outside_window = engine.check_news_blackout("2026-10-26T08:57:00+03:00")
    invalid = engine.check_news_blackout("not-a-time")

    assert before is not None and before.rule == "news_blackout"
    assert outside_window is None
    assert invalid is not None and invalid.rule == "invalid_decision_time"


def test_friday_close_uses_explicit_utc_decision_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.nexus_risk.rules_engine as rules_module

    monkeypatch.setattr(rules_module, "_AGGRESSIVE_TRADING", False)
    engine = RulesEngine()
    friday_after_close = datetime(2026, 10, 30, 20, 1, tzinfo=UTC)
    friday_before_close = datetime(2026, 10, 30, 19, 59, tzinfo=UTC)

    violation = engine.check_friday_close(friday_after_close)
    allowed = engine.check_friday_close(friday_before_close)

    assert violation is not None and violation.rule == "friday_close"
    assert allowed is None
    assert engine.check_friday_close("bad-time").rule == "invalid_decision_time"


def test_master_risk_check_passes_historical_decision_time_to_blackouts() -> None:
    engine = RulesEngine()
    engine._cfg.news_blackout_minutes = 5
    engine.set_upcoming_news([
        {"timestamp": "2026-10-26T06:03:00Z", "impact": "high"},
    ])
    proposal = TradeProposal(
        symbol="XAUUSD", direction=Verdict.BUY, entry=2400, sl=2390, tp1=2420,
        conviction=0.8,
    )

    _, violations = engine.check_all_rules(proposal, {
        "balance": 10_000,
        "open_positions_count": 0,
        "open_positions": [],
        "current_spread": 0.1,
        "avg_spread": 0.2,
        "expected_price": 2400,
        "actual_price": 2400,
        "decision_time": "2026-10-26T09:00:00+03:00",
    })
    assert any(v.rule == "news_blackout" for v in violations)
