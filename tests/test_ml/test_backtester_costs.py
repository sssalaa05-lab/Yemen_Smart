from __future__ import annotations

import numpy as np

from services.nexus_ml.backtester import SimpleBacktester


def test_backtest_reports_gross_net_and_itemized_cost_assumptions() -> None:
    engine = SimpleBacktester(
        spread_pips=2.0,
        pip_value=0.01,
        initial_capital=10_000.0,
        risk_per_trade=0.01,
        max_hold_bars=10,
        commission_per_round_trip=1.25,
        fees_per_round_trip=0.25,
        slippage_pips_per_side=0.5,
    )
    signals = np.array([1, 0])
    ohlcv = np.array([
        [100.0, 101.0, 99.0, 100.0, 10.0],
        [100.0, 102.0, 100.0, 101.0, 12.0],
    ])
    result = engine.backtest(signals, ohlcv)
    trade = result.trade_log[0]
    assert trade["gross_pnl"] > 0
    assert trade["pnl_usd"] < trade["gross_pnl"]
    assert trade["total_costs"] == (
        trade["spread_cost"] + trade["slippage_cost"]
        + trade["commission_cost"] + trade["fees_cost"]
    )
    assert result.net_pnl == sum(t["pnl_usd"] for t in result.trade_log)
    assert result.gross_pnl == sum(t["gross_pnl"] for t in result.trade_log)
    assert result.total_costs == result.gross_pnl - result.net_pnl
    assert result.cost_assumptions["slippage_pips_per_side"] == 0.5
