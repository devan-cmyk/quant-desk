"""Symbol selection ranks the universe and qualifies the positive-edge names."""
from quant_desk.selection.selector import select_symbols
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def test_select_qualifies_positive_symbols(multi_session):
    def data_fn(sym):
        if sym == "BAD":
            raise RuntimeError("no data")
        return multi_session
    res = select_symbols(
        ["AAA", "BBB", "BAD"], OpeningRangeBreakout, {"or_minutes": [30], "target_r": [1.5, 2.0]},
        data_fn=data_fn, is_sessions=3, oos_sessions=2, min_profit_factor=1.0, min_trades=1,
    )
    assert "AAA" in res["qualified"] and "BBB" in res["qualified"]   # breakout sessions are profitable
    assert "BAD" not in res["qualified"]
    assert any("error" in r for r in res["ranking"])
    # ranking sorted by profit factor desc
    pfs = [r.get("profit_factor") or 0 for r in res["ranking"] if "error" not in r]
    assert pfs == sorted(pfs, reverse=True)
    # validated params exposed per qualified symbol (carried from the latest WF fold)
    assert "AAA" in res["selected_params"]
    assert "target_r" in res["selected_params"]["AAA"]
