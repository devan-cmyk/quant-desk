"""Walk-forward: rolls IS→OOS, returns folds + an aggregate out-of-sample curve."""
from quant_desk.backtest.walkforward import walk_forward
from quant_desk.config import RiskLimits
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def test_walk_forward_produces_oos(multi_session):
    res = walk_forward(
        multi_session, OpeningRangeBreakout,
        {"or_minutes": [30], "target_r": [1.5, 2.0]},
        is_sessions=3, oos_sessions=2,
        limits=RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01,
                          max_daily_loss_pct=0.05, max_position_pct=0.5),
    )
    assert res["n_folds"] >= 2
    assert "oos_metrics" in res and "total_return" in res["oos_metrics"]
    for f in res["folds"]:                       # each fold picked params + has OOS result
        assert f["best_params"]["target_r"] in (1.5, 2.0)
        assert "oos_return" in f
    # OOS curve is continuous and chained across folds
    assert len(res["oos_equity"]) > 0


def test_walk_forward_too_few_sessions(two_sessions):
    res = walk_forward(two_sessions, OpeningRangeBreakout, {"target_r": [2.0]},
                       is_sessions=15, oos_sessions=5)
    assert res.get("error")                      # not enough sessions → clean error, no crash
