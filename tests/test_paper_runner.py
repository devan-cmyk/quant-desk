"""Forward paper runner: processes bars, trades, persists, and is incremental (last_ts)."""
from quant_desk.config import RiskLimits
from quant_desk.live.paper_runner import run_forward
from quant_desk.live.portfolio import PaperPortfolio
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def _limits():
    return RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_daily_loss_pct=0.05,
                      max_position_pct=0.5)


def test_paper_run_trades_and_persists(two_sessions, tmp_path):
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    res = run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                      portfolio=pf, limits=_limits(), max_bars=None)
    assert res["bars_processed"] == len(two_sessions)
    assert res["blotter_n"] == 2                 # one ORB trade per session, both flattened
    assert pf.last_ts is not None

    # save/load roundtrip keeps the account intact
    p = tmp_path / "state.json"
    pf.save(str(p))
    pf2 = PaperPortfolio.load(str(p))
    assert pf2.cash == pf.cash and pf2.blotter == pf.blotter and pf2.last_ts == pf.last_ts


def test_paper_run_uses_per_symbol_params(two_sessions):
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    res = run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                      portfolio=pf, limits=_limits(),
                      params_by_symbol={"AAA": {"or_minutes": 30, "target_r": 1.0}})
    assert res["bars_processed"] == len(two_sessions)
    assert res["blotter_n"] >= 1                  # runs + trades with the supplied params


def test_paper_run_is_incremental(two_sessions):
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                portfolio=pf, limits=_limits())
    # second run over the same data processes no new bars (last_ts advanced)
    res2 = run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                       portfolio=pf, limits=_limits())
    assert res2["bars_processed"] == 0
