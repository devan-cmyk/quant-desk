"""End-to-end: the engine runs, takes the ORB trade, and reports metrics."""
from quant_desk.backtest.engine import run_backtest
from quant_desk.config import RiskLimits
from quant_desk.risk.engine import RiskEngine
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def _risk():
    return RiskEngine(limits=RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01,
                                        max_daily_loss_pct=0.05, max_position_pct=0.5), equity=100_000)


def test_backtest_takes_trade_and_reports(breakout_session):
    res = run_backtest(breakout_session, OpeningRangeBreakout(), _risk())
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["side"] == "long" and t["reason"] in ("target", "stop", "eod")
    assert t["pnl"] > 0                          # breakout climbs into target
    m = res["metrics"]
    for k in ("total_return", "max_drawdown", "win_rate", "num_trades"):
        assert k in m
    assert m["num_trades"] == 1


def test_backtest_two_sessions(two_sessions):
    res = run_backtest(two_sessions, OpeningRangeBreakout(), _risk())
    assert len(res["trades"]) == 2              # one trade per session
    assert len(res["equity"]) == len(two_sessions)
