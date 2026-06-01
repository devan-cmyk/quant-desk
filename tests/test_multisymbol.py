"""Multi-symbol harness runs WF per symbol (offline via injected data_fn), pools trades,
runs pooled Monte-Carlo, and survives a failing symbol."""
from quant_desk.backtest.multisymbol import multi_symbol_walkforward
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def test_multisymbol_runs_and_pools(multi_session):
    def data_fn(sym):
        if sym == "BAD":
            raise RuntimeError("no data")
        return multi_session
    res = multi_symbol_walkforward(
        ["AAA", "BBB", "BAD"], OpeningRangeBreakout, {"or_minutes": [30], "target_r": [1.5, 2.0]},
        data_fn=data_fn, is_sessions=3, oos_sessions=2, mc_sims=500,
    )
    assert res["summary"]["symbols_run"] == 2          # AAA, BBB
    assert res["summary"]["symbols_failed"] == 1        # BAD
    assert any("error" in r for r in res["per_symbol"])
    assert res["summary"]["pooled_oos_trades"] >= 3
    mc = res["pooled_monte_carlo"]
    assert "prob_profit" in mc and "prob_ruin" in mc and mc["n_trades"] >= 3
